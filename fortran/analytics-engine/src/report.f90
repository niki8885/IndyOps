! Orchestration: decode the numeric request, run the indicator/risk cores

module report_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use json_mod
    use sort_stats_mod, only : mean_f
    use indicators_mod, only : indicators_t, compute_indicators
    use risk_mod, only : var_t, mc_t, states_t, value_at_risk, monte_carlo_gbm, volatility_regimes, volume_heatmap
    implicit none
    private
    public :: build_report

contains

    subroutine kv_raw(b, key)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        call jb_push(b, '"')
        call jb_push(b, key)
        call jb_push(b, '":')
    end subroutine kv_raw

    subroutine kvf(b, key, val)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: val
        call kv_raw(b, key)
        call jb_f64(b, val)
    end subroutine kvf

    subroutine kvi(b, key, val)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        integer, intent(in) :: val
        call kv_raw(b, key)
        call jb_int(b, val)
    end subroutine kvi

    subroutine kvfa(b, key, arr, n)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        call kv_raw(b, key)
        call jb_f64_array(b, arr, n)
    end subroutine kvfa

    function build_report(buf) result(out)
        character(len = *), intent(in) :: buf
        character(len = :), allocatable :: out
        type(jbuilder) :: b
        type(indicators_t) :: ind
        type(var_t) :: var
        type(mc_t) :: mc
        type(states_t) :: st
        real(real64), allocatable :: price(:), volume(:)
        integer, allocatable :: weekday(:), hour(:), mask(:)
        real(real64) :: heat(7, 24)
        real(real64) :: liq, ent, top3
        logical :: f
        integer :: n, nv, nwd, nh, nm, window, horizon, n_paths, seed
        integer :: i, wd, tcnt
        real(real64) :: last, prev, change_pct, tmax, tmin, tavg, tsum

        ! decode numeric request
        window = get_int_or(buf, 'window', 10)
        call get_f64_array(buf, 'price', price, n)
        call get_f64_array(buf, 'volume', volume, nv)
        call get_int_array(buf, 'weekday', weekday, nwd)
        call get_int_array(buf, 'hour', hour, nh)
        call get_int_array(buf, 'last24_mask', mask, nm)
        call get_f64_scalar(buf, 'liquidity_last', liq, f)
        call get_f64_scalar(buf, 'entropy_last', ent, f)
        call get_f64_scalar(buf, 'top3_share_last', top3, f)
        horizon = get_int_or(buf, 'horizon', 24)
        n_paths = get_int_or(buf, 'n_paths', 500)
        seed = get_int_or(buf, 'seed', 42)

        if (n < 1) then
            out = ''
            return
        end if

        ! compute
        call compute_indicators(price, n, window, ind)
        var = value_at_risk(ind%returns, n)
        mc = monte_carlo_gbm(ind%returns, n, price(n), horizon, n_paths, seed)
        st = volatility_regimes(ind%volatility, n)
        call volume_heatmap(volume, weekday, hour, n, heat)

        ! headline stats
        last = price(n)
        if (n > 1) then
            prev = price(n - 1)
        else
            prev = last
        end if
        if (prev /= 0.0_real64) then
            change_pct = (last - prev) / prev * 100.0_real64
        else
            change_pct = nan64()
        end if
        tsum = 0.0_real64
        tcnt = 0
        tmax = nan64()
        tmin = nan64()
        do i = 1, min(n, nm)
            if (mask(i) /= 0) then
                if (tcnt == 0) then
                    tmax = price(i)
                    tmin = price(i)
                else
                    if (price(i) > tmax) tmax = price(i)
                    if (price(i) < tmin) tmin = price(i)
                end if
                tsum = tsum + price(i)
                tcnt = tcnt + 1
            end if
        end do
        if (tcnt > 0) then
            tavg = tsum / real(tcnt, real64)
        else
            tavg = nan64()
        end if

        ! emit
        call jb_init(b)
        call jb_push(b, '{')

        ! series
        call jb_push(b, '"series":{')
        call kvfa(b, 'sma', ind%sma, n);                 call jb_push(b, ',')
        call kvfa(b, 'bb_upper', ind%bb_upper, n);       call jb_push(b, ',')
        call kvfa(b, 'bb_lower', ind%bb_lower, n);       call jb_push(b, ',')
        call kvfa(b, 'rsi', ind%rsi, n);                 call jb_push(b, ',')
        call kvfa(b, 'macd', ind%macd, n);               call jb_push(b, ',')
        call kvfa(b, 'macd_signal', ind%macd_signal, n); call jb_push(b, ',')
        call kvfa(b, 'macd_hist', ind%macd_hist, n);     call jb_push(b, ',')
        call kvfa(b, 'returns', ind%returns, n);         call jb_push(b, ',')
        call kvfa(b, 'volatility', ind%volatility, n);   call jb_push(b, ',')
        call kvfa(b, 'tenkan', ind%tenkan, n);           call jb_push(b, ',')
        call kvfa(b, 'kijun', ind%kijun, n);             call jb_push(b, ',')
        call kvfa(b, 'senkou_a', ind%senkou_a, n);       call jb_push(b, ',')
        call kvfa(b, 'senkou_b', ind%senkou_b, n)
        call jb_push(b, '},')

        ! stats
        call jb_push(b, '"stats":{')
        call kvf(b, 'last', last);             call jb_push(b, ',')
        call kvf(b, 'change_pct', change_pct); call jb_push(b, ',')
        call kvf(b, 'today_max', tmax);        call jb_push(b, ',')
        call kvf(b, 'today_min', tmin);        call jb_push(b, ',')
        call kvf(b, 'today_avg', tavg);        call jb_push(b, ',')
        call kvf(b, 'all_max', maxval(price(1:n))); call jb_push(b, ',')
        call kvf(b, 'all_min', minval(price(1:n))); call jb_push(b, ',')
        call kvf(b, 'all_avg', mean_f(price, n));    call jb_push(b, ',')
        call kvf(b, 'volatility', ind%volatility(n)); call jb_push(b, ',')
        call kvf(b, 'liquidity', liq);         call jb_push(b, ',')
        call kvf(b, 'entropy', ent);           call jb_push(b, ',')
        call kvf(b, 'top3_share', top3);       call jb_push(b, ',')
        call kvi(b, 'points', n)
        call jb_push(b, '},')

        ! risk
        call jb_push(b, '"risk":{')
        call kvf(b, 'var95', var%var95);   call jb_push(b, ',')
        call kvf(b, 'cvar95', var%cvar95); call jb_push(b, ',')
        if (var%has_hist) then
            call kv_raw(b, 'hist_counts'); call jb_int_array(b, var%hist_counts, size(var%hist_counts))
            call jb_push(b, ',')
            call kvfa(b, 'hist_edges', var%hist_edges, size(var%hist_edges))
        else
            call jb_push(b, '"hist_counts":null,"hist_edges":null')
        end if
        call jb_push(b, '},')

        ! montecarlo
        if (mc%has) then
            call jb_push(b, '"montecarlo":{')
            call kvi(b, 'horizon', mc%horizon);    call jb_push(b, ',')
            call kvfa(b, 'p5', mc%p5, mc%horizon);  call jb_push(b, ',')
            call kvfa(b, 'p50', mc%p50, mc%horizon); call jb_push(b, ',')
            call kvfa(b, 'p95', mc%p95, mc%horizon); call jb_push(b, ',')
            call kvf(b, 'final_p5', mc%final_p5);   call jb_push(b, ',')
            call kvf(b, 'final_p50', mc%final_p50); call jb_push(b, ',')
            call kvf(b, 'final_p95', mc%final_p95)
            call jb_push(b, '},')
        else
            call jb_push(b, '"montecarlo":null,')
        end if

        ! heatmap (7 rows × 24)
        call jb_push(b, '"heatmap":[')
        do wd = 1, 7
            if (wd > 1) call jb_push(b, ',')
            call jb_f64_array(b, heat(wd, :), 24)
        end do
        call jb_push(b, '],')

        ! states
        if (st%has) then
            call jb_push(b, '"states":{')
            call jb_push(b, '"labels":[')
            do i = 1, n
                if (i > 1) call jb_push(b, ',')
                if (st%labels(i) < 0) then
                    call jb_push(b, 'null')
                else
                    call jb_int(b, st%labels(i))
                end if
            end do
            call jb_push(b, '],')
            call jb_push(b, '"names":["Calm","Normal","Turbulent"],')
            call kv_raw(b, 'current')
            if (st%current < 0) then
                call jb_push(b, 'null')
            else
                call jb_int(b, st%current)
            end if
            call jb_push(b, ',')
            call kv_raw(b, 'thresholds')
            call jb_push(b, '[')
            call jb_f64(b, st%q1); call jb_push(b, ','); call jb_f64(b, st%q2)
            call jb_push(b, '],')
            call kv_raw(b, 'counts')
            call jb_int_array(b, st%counts, 3)
            call jb_push(b, '}')
        else
            call jb_push(b, '"states":null')
        end if

        call jb_push(b, '}')
        out = jb_str(b)
    end function build_report

end module report_mod
