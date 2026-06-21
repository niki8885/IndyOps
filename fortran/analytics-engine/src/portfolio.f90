module portfolio_mod
    !! Markowitz mean-variance portfolio optimiser on the budget simplex with a

    use, intrinsic :: iso_fortran_env, only : real64
    use json_mod, only : get_f64_array, get_f64_scalar, &
            jbuilder, jb_init, jb_push, jb_str, jb_f64, jb_f64_array
    implicit none
    private
    public :: build_portfolio_report, optimize_weights

    real(real64), parameter :: SIGMA_FLOOR = 1.0e-6_real64
    real(real64), parameter :: LAMBDA_FLOOR = 1.0e-9_real64

contains

    function weight_sum(mu, s2, lambda, nu) result(ssum)
        real(real64), intent(in) :: mu(:), s2(:), lambda, nu
        real(real64) :: ssum
        ssum = sum(max(0.0_real64, (mu - nu) / (lambda * s2)))
    end function weight_sum

    subroutine optimize_weights(mu, sigma, lambda_in, w)
        real(real64), intent(in) :: mu(:), sigma(:), lambda_in
        real(real64), allocatable, intent(out) :: w(:)
        real(real64), allocatable :: s2(:)
        real(real64) :: lambda, nu_lo, nu_hi, nu, step, ssum
        integer :: n, it

        n = size(mu)
        allocate(w(n))
        if (n == 0) return
        if (n == 1) then
            w(1) = 1.0_real64
            return
        end if

        lambda = max(lambda_in, LAMBDA_FLOOR)
        allocate(s2(n))
        s2 = max(sigma, SIGMA_FLOOR) ** 2

        ! bracket nu: sum(w) -> 0 at nu = max(mu)
        nu_hi = maxval(mu)
        step = lambda * maxval(s2)
        if (step <= 0.0_real64) step = 1.0_real64
        nu_lo = nu_hi - step
        do while (weight_sum(mu, s2, lambda, nu_lo) < 1.0_real64)
            step = step * 2.0_real64
            nu_lo = nu_lo - step
        end do

        do it = 1, 200
            nu = 0.5_real64 * (nu_lo + nu_hi)
            ssum = weight_sum(mu, s2, lambda, nu)
            if (ssum > 1.0_real64) then
                nu_lo = nu
            else
                nu_hi = nu
            end if
        end do
        nu = 0.5_real64 * (nu_lo + nu_hi)

        w = max(0.0_real64, (mu - nu) / (lambda * s2))
        ssum = sum(w)
        if (ssum > 0.0_real64) w = w / ssum     ! clean tiny residual so sum == 1
    end subroutine optimize_weights

    function build_portfolio_report(buf) result(out)
        character(len = *), intent(in) :: buf
        character(len = :), allocatable :: out
        real(real64), allocatable :: mu(:), sigma(:), w(:)
        real(real64) :: lambda, exp_ret, variance, stddev
        logical :: found
        integer :: nmu, nsig, n
        type(jbuilder) :: b

        call get_f64_array(buf, 'mu', mu, nmu)
        call get_f64_array(buf, 'sigma', sigma, nsig)
        call get_f64_scalar(buf, 'risk_aversion', lambda, found)
        if (.not. found) lambda = 1.0_real64

        n = min(nmu, nsig)
        if (n <= 0) then
            out = ''
            return
        end if

        call optimize_weights(mu(1:n), sigma(1:n), lambda, w)
        exp_ret = sum(mu(1:n) * w)
        variance = sum((max(sigma(1:n), SIGMA_FLOOR) ** 2) * (w ** 2))
        stddev = sqrt(max(variance, 0.0_real64))

        call jb_init(b)
        call jb_push(b, '{"weights":')
        call jb_f64_array(b, w, n)
        call jb_push(b, ',"exp_return":')
        call jb_f64(b, exp_ret)
        call jb_push(b, ',"variance":')
        call jb_f64(b, variance)
        call jb_push(b, ',"stddev":')
        call jb_f64(b, stddev)
        call jb_push(b, '}')
        out = jb_str(b)
    end function build_portfolio_report

end module portfolio_mod
