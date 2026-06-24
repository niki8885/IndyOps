! Demand metrics - native core

module demand_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_is_nan, ieee_is_finite
    use json_mod
    use sort_stats_mod, only : sort_asc, percentile_linear, mean_f, std_f
    implicit none
    private
    public :: build_demand

contains

    ! mean of the last days elements, skipping NaN
    function tail_mean(a, n, days) result(r)
        real(real64), intent(in) :: a(:)
        integer, intent(in) :: n, days
        real(real64) :: r, s
        integer :: i, lo, cnt
        lo = max(1, n - days + 1)
        s = 0.0_real64; cnt = 0
        do i = lo, n
            if (.not. ieee_is_nan(a(i))) then
                s = s + a(i); cnt = cnt + 1
            end if
        end do
        if (cnt > 0) then; r = s / real(cnt, real64);
        else; r = nan64();
        end if
    end function tail_mean

    ! mean over an inclusive 1-based slice [lo,hi], skipping NaN
    function slice_mean(a, lo, hi) result(r)
        real(real64), intent(in) :: a(:)
        integer, intent(in) :: lo, hi
        real(real64) :: r, s
        integer :: i, cnt
        s = 0.0_real64; cnt = 0
        do i = lo, hi
            if (.not. ieee_is_nan(a(i))) then
                s = s + a(i); cnt = cnt + 1
            end if
        end do
        if (cnt > 0) then; r = s / real(cnt, real64);
        else; r = nan64();
        end if
    end function slice_mean

    ! median of the last `days` elements, skipping NaN
    function tail_median(a, n, days) result(r)
        real(real64), intent(in) :: a(:)
        integer, intent(in) :: n, days
        real(real64) :: r
        real(real64), allocatable :: c(:)
        integer :: i, lo, m
        lo = max(1, n - days + 1)
        allocate(c(n - lo + 1)); m = 0
        do i = lo, n
            if (.not. ieee_is_nan(a(i))) then
                m = m + 1; c(m) = a(i)
            end if
        end do
        if (m == 0) then; r = nan64(); return;
        end if
        call sort_asc(c, 1, m)
        r = percentile_linear(c, m, 50.0_real64)
    end function tail_median

    ! std (ddof=1) and mean of the last `days` non-NaN elements
    subroutine tail_std_mean(a, n, days, sd, mu, cnt)
        real(real64), intent(in) :: a(:)
        integer, intent(in) :: n, days
        real(real64), intent(out) :: sd, mu
        integer, intent(out) :: cnt
        real(real64), allocatable :: c(:)
        integer :: i, lo
        lo = max(1, n - days + 1)
        allocate(c(n - lo + 1)); cnt = 0
        do i = lo, n
            if (.not. ieee_is_nan(a(i))) then
                cnt = cnt + 1; c(cnt) = a(i)
            end if
        end do
        if (cnt == 0) then
            mu = nan64(); sd = nan64()
        else
            mu = mean_f(c, cnt)
            sd = std_f(c, cnt, 1)
        end if
    end subroutine tail_std_mean

    ! OLS degree-1 fit of y vs x=0..n-1 → slope, intercept
    pure subroutine ols1(y, n, slope, intercept)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n
        real(real64), intent(out) :: slope, intercept
        real(real64) :: xbar, ybar, sxy, sxx, xi
        integer :: i
        xbar = real(n - 1, real64) / 2.0_real64
        ybar = sum(y(1:n)) / real(n, real64)
        sxy = 0.0_real64; sxx = 0.0_real64
        do i = 1, n
            xi = real(i - 1, real64) - xbar
            sxy = sxy + xi * (y(i) - ybar)
            sxx = sxx + xi * xi
        end do
        if (sxx == 0.0_real64) then
            slope = 0.0_real64
        else
            slope = sxy / sxx
        end if
        intercept = ybar - slope * xbar
    end subroutine ols1

    function clamp01(x) result(r)
        real(real64), intent(in) :: x
        real(real64) :: r
        r = max(0.0_real64, min(1.0_real64, x))
    end function clamp01

    ! emit "key":value as a finite-or-null
    subroutine kvf(b, key, val, sep)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: val
        logical, intent(in) :: sep
        call jb_push(b, '"'); call jb_push(b, key); call jb_push(b, '":')
        call jb_f64(b, val)
        if (sep) call jb_push(b, ',')
    end subroutine kvf

    subroutine kvarr(b, key, arr, n, sep)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        logical, intent(in) :: sep
        call jb_push(b, '"'); call jb_push(b, key); call jb_push(b, '":')
        call jb_f64_array(b, arr, n)
        if (sep) call jb_push(b, ',')
    end subroutine kvarr

    function build_demand(buf) result(out)
        character(len = *), intent(in) :: buf
        character(len = :), allocatable :: out
        type(jbuilder) :: b

        real(real64), allocatable :: price(:), vol(:), oc(:)
        integer, allocatable :: wd(:)
        real(real64), allocatable :: turnover(:), ma7(:), tline(:), vfill(:), logy(:)
        real(real64) :: wkm(0:6)
        integer :: n, np, nv, noc, nwd, i, j, lo, cnt, total, k, kcnt
        real(real64) :: adv7, adv30, adv90, prev30, isk_day, active, last_vol
        real(real64) :: vol_cv, sd30, mu30, spike, slope, intercept, ptp
        real(real64) :: momentum, trend_pct30, weekend_lift, wautoc
        real(real64) :: wk_acc, we_acc, swin, ymin, ymax
        integer :: wk_cnt, we_cnt, sc
        real(real64) :: bid_depth, ask_depth, best_bid, best_ask, spr, spr_pct, mid
        real(real64) :: denom, imbalance, demand_cov, supply_cov, bid_isk
        real(real64) :: liq, consist, trend_norm, total_score
        real(real64) :: m1, m2, c1, c2, cov, v1, v2
        logical :: f

        call get_f64_array(buf, 'price', price, np)
        call get_f64_array(buf, 'volume', vol, nv)
        call get_f64_array(buf, 'order_count', oc, noc)
        call get_int_array(buf, 'weekday', wd, nwd)
        n = nv
        if (n < 1) then
            out = ''
            return
        end if
        if (np < n) then; allocate(price(n)); price = nan64();
        end if
        if (noc < n) then; allocate(oc(n)); oc = nan64();
        end if

        ! derived series
        allocate(turnover(n), ma7(n), tline(n), vfill(n), logy(n))
        do i = 1, n
            if (ieee_is_nan(vol(i)) .or. ieee_is_nan(price(i))) then
                turnover(i) = nan64()
            else
                turnover(i) = vol(i) * price(i)
            end if
            if (ieee_is_nan(vol(i))) then; vfill(i) = 0.0_real64;
            else; vfill(i) = vol(i);
            end if
            logy(i) = log(1.0_real64 + vfill(i))
        end do
        ! rolling-7 mean, min_periods=1
        do i = 1, n
            lo = max(1, i - 6); swin = 0.0_real64; cnt = 0
            do j = lo, i
                if (.not. ieee_is_nan(vol(j))) then; swin = swin + vol(j); cnt = cnt + 1;
                end if
            end do
            if (cnt > 0) then; ma7(i) = swin / real(cnt, real64);
            else; ma7(i) = nan64();
            end if
        end do

        ! throughput
        adv7 = tail_mean(vol, n, 7)
        adv30 = tail_mean(vol, n, 30)
        adv90 = tail_mean(vol, n, 90)
        isk_day = tail_mean(turnover, n, 30)
        if (n >= 60) then; prev30 = slice_mean(vol, n - 59, n - 30);
        else; prev30 = nan64();
        end if

        ! active-days ratio over last 90
        lo = max(1, n - 90 + 1); total = n - lo + 1; cnt = 0
        do i = lo, n
            if (.not. ieee_is_nan(vol(i))) then
                if (vol(i) > 0.0_real64) cnt = cnt + 1
            end if
        end do
        if (total > 0) then; active = real(cnt, real64) / real(total, real64);
        else; active = nan64();
        end if

        last_vol = vol(n)
        call tail_std_mean(vol, n, 30, sd30, mu30, sc)
        if (sc > 1 .and. .not. ieee_is_nan(mu30) .and. mu30 /= 0.0_real64) then
            vol_cv = sd30 / mu30
        else
            vol_cv = nan64()
        end if
        if (.not. ieee_is_nan(last_vol) .and. sc > 1 .and. sd30 /= 0.0_real64) then
            spike = (last_vol - mu30) / sd30
        else
            spike = nan64()
        end if

        ! trend slope + line on log1p(volume)
        if (n < 5) then
            slope = nan64()
            do i = 1, n; tline(i) = nan64();
            end do
        else
            ymin = minval(logy(1:n)); ymax = maxval(logy(1:n)); ptp = ymax - ymin
            call ols1(logy, n, slope, intercept)
            if (ptp == 0.0_real64) slope = 0.0_real64
            do i = 1, n
                tline(i) = exp(intercept + slope * real(i - 1, real64)) - 1.0_real64
            end do
        end if

        if (.not. ieee_is_nan(adv30) .and. .not. ieee_is_nan(prev30) .and. prev30 /= 0.0_real64) then
            trend_pct30 = adv30 / prev30 - 1.0_real64
        else
            trend_pct30 = nan64()
        end if
        if (.not. ieee_is_nan(adv7) .and. .not. ieee_is_nan(adv30) .and. adv30 /= 0.0_real64) then
            momentum = adv7 / adv30
        else
            momentum = nan64()
        end if

        ! weekday seasonality
        do k = 0, 6
            wk_acc = 0.0_real64; kcnt = 0
            do i = 1, n
                if (i <= nwd) then
                    if (wd(i) == k .and. .not. ieee_is_nan(vol(i))) then
                        wk_acc = wk_acc + vol(i); kcnt = kcnt + 1
                    end if
                end if
            end do
            if (kcnt > 0) then; wkm(k) = wk_acc / real(kcnt, real64);
            else; wkm(k) = nan64();
            end if
        end do
        ! weekend lift = nanmean(weekend group means) / nanmean(weekday group means)
        wk_acc = 0.0_real64; wk_cnt = 0
        do k = 0, 4
            if (.not. ieee_is_nan(wkm(k))) then; wk_acc = wk_acc + wkm(k); wk_cnt = wk_cnt + 1;
            end if
        end do
        we_acc = 0.0_real64; we_cnt = 0
        do k = 5, 6
            if (.not. ieee_is_nan(wkm(k))) then; we_acc = we_acc + wkm(k); we_cnt = we_cnt + 1;
            end if
        end do
        if (wk_cnt > 0 .and. we_cnt > 0 .and. wk_acc /= 0.0_real64) then
            weekend_lift = (we_acc / real(we_cnt, real64)) / (wk_acc / real(wk_cnt, real64))
        else
            weekend_lift = nan64()
        end if

        ! weekly autocorrelation (Pearson, lag 7, on NaN-filled-zero volume)
        if (n >= 14) then
            j = n - 7
            m1 = sum(vfill(8:n)) / real(j, real64)
            m2 = sum(vfill(1:j)) / real(j, real64)
            cov = 0.0_real64; v1 = 0.0_real64; v2 = 0.0_real64
            do i = 1, j
                c1 = vfill(i + 7) - m1; c2 = vfill(i) - m2
                cov = cov + c1 * c2; v1 = v1 + c1 * c1; v2 = v2 + c2 * c2
            end do
            if (v1 > 0.0_real64 .and. v2 > 0.0_real64) then
                wautoc = cov / sqrt(v1 * v2)
            else
                wautoc = nan64()
            end if
        else
            wautoc = nan64()
        end if

        ! order-book pressure (primitives passed in as scalars)
        call get_f64_scalar(buf, 'book_bid_depth', bid_depth, f); if (.not. f) bid_depth = 0.0_real64
        if (ieee_is_nan(bid_depth)) bid_depth = 0.0_real64
        call get_f64_scalar(buf, 'book_ask_depth', ask_depth, f); if (.not. f) ask_depth = 0.0_real64
        if (ieee_is_nan(ask_depth)) ask_depth = 0.0_real64
        call get_f64_scalar(buf, 'book_best_bid', best_bid, f)
        call get_f64_scalar(buf, 'book_best_ask', best_ask, f)
        call get_f64_scalar(buf, 'book_spread', spr, f)
        call get_f64_scalar(buf, 'book_spread_pct', spr_pct, f)
        call get_f64_scalar(buf, 'book_mid', mid, f)
        denom = bid_depth + ask_depth
        if (denom /= 0.0_real64) then; imbalance = (bid_depth - ask_depth) / denom;
        else; imbalance = nan64();
        end if
        if (.not. ieee_is_nan(adv30) .and. adv30 /= 0.0_real64 .and. bid_depth /= 0.0_real64) then
            demand_cov = bid_depth / adv30
        else
            demand_cov = nan64()
        end if
        if (.not. ieee_is_nan(adv30) .and. adv30 /= 0.0_real64 .and. ask_depth /= 0.0_real64) then
            supply_cov = ask_depth / adv30
        else
            supply_cov = nan64()
        end if
        if (ieee_is_finite(best_bid)) then; bid_isk = bid_depth * best_bid;
        else; bid_isk = nan64();
        end if

        ! transparent 0-100 demand score
        if (ieee_is_nan(isk_day)) then; liq = clamp01(log10(1.0_real64) / 11.0_real64)
        else; liq = clamp01(log10(isk_day + 1.0_real64) / 11.0_real64);
        end if
        if (ieee_is_nan(active)) then; consist = 0.0_real64;
        else; consist = active;
        end if
        if (ieee_is_nan(slope)) then; trend_norm = clamp01(0.5_real64)
        else; trend_norm = clamp01(0.5_real64 + slope * 10.0_real64);
        end if
        total_score = 100.0_real64 * (0.5_real64 * liq + 0.3_real64 * consist + 0.2_real64 * trend_norm)

        ! emit
        call jb_init(b)
        call jb_push(b, '{"series":{')
        call kvarr(b, 'volume', vol, n, .true.)
        call kvarr(b, 'volume_ma7', ma7, n, .true.)
        call kvarr(b, 'isk_turnover', turnover, n, .true.)
        call kvarr(b, 'order_count', oc, n, .true.)
        call kvarr(b, 'trend_line', tline, n, .false.)
        call jb_push(b, '},"stats":{')
        call kvf(b, 'adv7', adv7, .true.)
        call kvf(b, 'adv30', adv30, .true.)
        call kvf(b, 'adv90', adv90, .true.)
        call kvf(b, 'median30', tail_median(vol, n, 30), .true.)
        call kvf(b, 'isk_per_day', isk_day, .true.)
        call kvf(b, 'active_days_ratio', active, .true.)
        call kvf(b, 'avg_order_count', tail_mean(oc, n, 30), .true.)
        call kvf(b, 'last_volume', last_vol, .true.)
        call kvf(b, 'trend_slope', slope, .true.)
        call kvf(b, 'trend_pct_30', trend_pct30, .true.)
        call kvf(b, 'momentum', momentum, .true.)
        call kvf(b, 'volume_cv', vol_cv, .true.)
        call kvf(b, 'spike_z', spike, .true.)
        call jb_push(b, '"points":'); call jb_int(b, n)
        call jb_push(b, '},"book":{')
        call kvf(b, 'best_bid', best_bid, .true.)
        call kvf(b, 'best_ask', best_ask, .true.)
        call kvf(b, 'spread', spr, .true.)
        call kvf(b, 'spread_pct', spr_pct, .true.)
        call kvf(b, 'mid', mid, .true.)
        call kvf(b, 'bid_depth', bid_depth, .true.)
        call kvf(b, 'ask_depth', ask_depth, .true.)
        call kvf(b, 'bid_isk', bid_isk, .true.)
        call kvf(b, 'imbalance', imbalance, .true.)
        call kvf(b, 'demand_coverage_days', demand_cov, .true.)
        call kvf(b, 'supply_coverage_days', supply_cov, .false.)
        call jb_push(b, '},')
        call kvarr(b, 'weekday_volume', wkm, 7, .true.)
        call kvf(b, 'weekend_lift', weekend_lift, .true.)
        call kvf(b, 'weekly_autocorr', wautoc, .true.)
        call jb_push(b, '"score":{')
        call kvf(b, 'total', total_score, .true.)
        call kvf(b, 'liquidity', liq, .true.)
        call kvf(b, 'consistency', consist, .true.)
        call kvf(b, 'trend', trend_norm, .false.)
        call jb_push(b, '}}')
        out = jb_str(b)
    end function build_demand

end module demand_mod
