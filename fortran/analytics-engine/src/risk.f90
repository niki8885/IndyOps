! Risk analytics
module risk_mod
  use, intrinsic :: iso_fortran_env, only: real64
  use, intrinsic :: ieee_arithmetic, only: ieee_is_nan
  use json_mod, only: nan64
  use sort_stats_mod, only: drop_nan, sort_asc, percentile_linear, quantile_copy, mean_f, std_f, histogram_np
  use rng_mod, only: rng_t, rng_seed, rng_normal
  implicit none
  private
  public :: var_t, mc_t, states_t, value_at_risk, monte_carlo_gbm, volatility_regimes, volume_heatmap

  type :: var_t
     real(real64) :: var95 = 0.0_real64
     real(real64) :: cvar95 = 0.0_real64
     logical :: has_hist = .false.
     integer, allocatable :: hist_counts(:)
     real(real64), allocatable :: hist_edges(:)
  end type var_t

  type :: mc_t
     logical :: has = .false.
     integer :: horizon = 0
     real(real64), allocatable :: p5(:), p50(:), p95(:)
     real(real64) :: final_p5 = 0.0_real64, final_p50 = 0.0_real64, final_p95 = 0.0_real64
  end type mc_t

  type :: states_t
     logical :: has = .false.
     integer, allocatable :: labels(:)      ! 0/1/2 per point, -1 = unlabelled (null)
     integer :: current = -1                ! 0/1/2, or -1 (null)
     real(real64) :: q1 = 0.0_real64, q2 = 0.0_real64
     integer :: counts(3) = 0
  end type states_t

contains

  ! Accurate log(1+x) (Kahan)
  pure function log1p(x) result(r)
    real(real64), intent(in) :: x
    real(real64) :: r, u
    u = 1.0_real64 + x
    if (u == 1.0_real64) then
       r = x
    else
       r = log(u) * (x / (u - 1.0_real64))
    end if
  end function log1p

  function value_at_risk(returns, n) result(v)
    real(real64), intent(in) :: returns(:)
    integer, intent(in) :: n
    type(var_t) :: v
    real(real64), allocatable :: rclean(:)
    integer :: m, i, ntail, nbins
    real(real64) :: tail_sum

    v%var95 = nan64()
    v%cvar95 = nan64()
    call drop_nan(returns, n, rclean, m)
    if (m < 5) return

    call sort_asc(rclean, 1, m)
    v%var95 = percentile_linear(rclean, m, 5.0_real64)
    tail_sum = 0.0_real64
    ntail = 0
    do i = 1, m
       if (rclean(i) <= v%var95) then
          tail_sum = tail_sum + rclean(i)
          ntail = ntail + 1
       end if
    end do
    if (ntail > 0) then
       v%cvar95 = tail_sum / real(ntail, real64)
    else
       v%cvar95 = v%var95
    end if

    nbins = min(30, max(10, m / 3))
    call histogram_np(rclean, m, nbins, v%hist_counts, v%hist_edges)
    v%has_hist = .true.
  end function value_at_risk

  function monte_carlo_gbm(returns, n, last_price, horizon, n_paths, seed) result(mc)
    real(real64), intent(in) :: returns(:)
    integer, intent(in) :: n, horizon, n_paths, seed
    real(real64), intent(in) :: last_price
    type(mc_t) :: mc
    real(real64), allocatable :: rclean(:), logret(:), paths(:,:), col(:)
    real(real64) :: mu, sigma, cum
    integer :: m, p, j
    type(rng_t) :: rng

    call drop_nan(returns, n, rclean, m)
    if (m < 10) return

    allocate(logret(m))
    do j = 1, m
       logret(j) = log1p(rclean(j))
    end do
    mu = mean_f(logret, m)
    sigma = std_f(logret, m, 0)          ! np.std → ddof=0

    call rng_seed(rng, seed)
    allocate(paths(n_paths, horizon))
    do p = 1, n_paths                    ! row-major draw order, like numpy
       cum = 0.0_real64
       do j = 1, horizon
          cum = cum + rng_normal(rng, mu, sigma)
          paths(p, j) = last_price * exp(cum)
       end do
    end do

    mc%has = .true.
    mc%horizon = horizon
    allocate(mc%p5(horizon), mc%p50(horizon), mc%p95(horizon))
    allocate(col(n_paths))
    do j = 1, horizon
       col = paths(:, j)
       mc%p5(j) = quantile_copy(col, n_paths, 5.0_real64)
       mc%p50(j) = quantile_copy(col, n_paths, 50.0_real64)
       mc%p95(j) = quantile_copy(col, n_paths, 95.0_real64)
    end do
    mc%final_p5 = mc%p5(horizon)
    mc%final_p50 = mc%p50(horizon)
    mc%final_p95 = mc%p95(horizon)
  end function monte_carlo_gbm

  function volatility_regimes(volatility, n) result(s)
    real(real64), intent(in) :: volatility(:)
    integer, intent(in) :: n
    type(states_t) :: s
    real(real64), allocatable :: vclean(:)
    integer :: m, i
    real(real64) :: v

    call drop_nan(volatility, n, vclean, m)
    if (m < 6) return

    s%has = .true.
    s%q1 = quantile_copy(vclean, m, 33.0_real64)
    s%q2 = quantile_copy(vclean, m, 66.0_real64)
    allocate(s%labels(n))
    s%counts = 0
    do i = 1, n
       v = volatility(i)
       if (ieee_is_nan(v)) then
          s%labels(i) = -1
       else if (v <= s%q1) then
          s%labels(i) = 0
       else if (v <= s%q2) then
          s%labels(i) = 1
       else
          s%labels(i) = 2
       end if
       if (s%labels(i) >= 0) then
          s%counts(s%labels(i) + 1) = s%counts(s%labels(i) + 1) + 1
          s%current = s%labels(i)        ! last non-null wins
       end if
    end do
  end function volatility_regimes

  ! 7×24 grid of mean volume; cells with no observations are NaN.
  subroutine volume_heatmap(volume, weekday, hour, n, heat)
    real(real64), intent(in) :: volume(:)
    integer, intent(in) :: weekday(:), hour(:)
    integer, intent(in) :: n
    real(real64), intent(out) :: heat(7, 24)
    real(real64) :: vsum(7, 24)
    integer :: cnt(7, 24)
    integer :: i, wd, hr
    vsum = 0.0_real64
    cnt = 0
    do i = 1, n
       if (ieee_is_nan(volume(i))) cycle
       wd = weekday(i)
       hr = hour(i)
       if (wd < 0 .or. wd > 6 .or. hr < 0 .or. hr > 23) cycle
       vsum(wd + 1, hr + 1) = vsum(wd + 1, hr + 1) + volume(i)
       cnt(wd + 1, hr + 1) = cnt(wd + 1, hr + 1) + 1
    end do
    do hr = 1, 24
       do wd = 1, 7
          if (cnt(wd, hr) > 0) then
             heat(wd, hr) = vsum(wd, hr) / real(cnt(wd, hr), real64)
          else
             heat(wd, hr) = nan64()
          end if
       end do
    end do
  end subroutine volume_heatmap

end module risk_mod
