! Scenario Simulation engine

module scenario_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use json_mod
    use sort_stats_mod, only : sort_asc, percentile_linear, mean_f, std_f, histogram_np
    use rng_mod, only : rng_t, rng_seed, rng_uniform, rng_normal, rng_chi2
    use distrib_mod, only : norm_cdf, norm_ppf, student_t_cdf, quantile_grid_interp
    implicit none
    private
    public :: build_scenario_report

    integer, parameter :: GRIDK = 101
    integer, parameter :: NBINS = 40

    type :: simctx
        integer :: n = 0, corr_mode = 0, dist_mode = 0, n_legs = 0, n_vars = 0, n_factors = 1
        integer :: slots = 1, copula = 0, garch = 0, path_steps = 1, production_time_s = 0
        real(real64) :: horizon_days = 1.0_real64, fixed_cost = 0.0_real64
        real(real64) :: participation_cap = 0.1_real64, shortfall_premium = 0.25_real64
        real(real64) :: slippage = 0.5_real64, haul_delay_prob = 0.0_real64
        real(real64) :: haul_delay_hours_mean = 0.0_real64, holding_daily_rate = 0.0_real64
        real(real64) :: risk_lambda = 1.0_real64, broker_fee_pct = 0.0_real64
        real(real64) :: sales_tax_pct = 0.0_real64, product_qty = 1.0_real64
        real(real64) :: t_df = 8.0_real64, garch_alpha = 0.08_real64, garch_beta = 0.90_real64
        real(real64), allocatable :: qty(:), mu(:), sigma(:), vol_mean(:), vol_sigma(:)
        real(real64), allocatable :: spread_mean(:), spread_sigma(:), idio_sigma(:), factor_sigma(:)
        real(real64), allocatable :: qgrid_flat(:), l_flat(:), loadings_flat(:)
        real(real64), allocatable :: ar_phi(:), step_sigma(:), theta(:), x0(:), garch_omega(:)
    end type simctx

contains

    ! JSON helpers

    subroutine kv_raw(b, key)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        call jb_push(b, '"'); call jb_push(b, key); call jb_push(b, '":')
    end subroutine kv_raw

    subroutine kvf(b, key, val)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: val
        call kv_raw(b, key); call jb_f64(b, val)
    end subroutine kvf

    subroutine kvi(b, key, val)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        integer, intent(in) :: val
        call kv_raw(b, key); call jb_int(b, val)
    end subroutine kvi

    subroutine emit_stat(b, key, arr, n)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        real(real64), allocatable :: c(:)
        allocate(c(n)); c = arr(1:n); call sort_asc(c, 1, n)
        call kv_raw(b, key); call jb_push(b, '{')
        call kvf(b, 'mean', mean_f(arr, n));                  call jb_push(b, ',')
        call kvf(b, 'p5', percentile_linear(c, n, 5.0_real64));   call jb_push(b, ',')
        call kvf(b, 'p50', percentile_linear(c, n, 50.0_real64)); call jb_push(b, ',')
        call kvf(b, 'p95', percentile_linear(c, n, 95.0_real64))
        call jb_push(b, '}')
    end subroutine emit_stat

    pure function tail_mean(sorted, n, thresh) result(r)
        real(real64), intent(in) :: sorted(:)
        integer, intent(in) :: n
        real(real64), intent(in) :: thresh
        real(real64) :: r, s
        integer :: i, cnt
        s = 0.0_real64; cnt = 0
        do i = 1, n
            if (sorted(i) <= thresh) then
                s = s + sorted(i); cnt = cnt + 1
            else
                exit
            end if
        end do
        if (cnt > 0) then
            r = s / real(cnt, real64)
        else
            r = thresh
        end if
    end function tail_mean

    subroutine emit_hist(b, key_c, key_e, arr, n)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key_c, key_e
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        integer, allocatable :: counts(:)
        real(real64), allocatable :: edges(:)
        call histogram_np(arr, n, NBINS, counts, edges)
        call kv_raw(b, key_c); call jb_int_array(b, counts, size(counts)); call jb_push(b, ',')
        call kv_raw(b, key_e); call jb_f64_array(b, edges, size(edges))
    end subroutine emit_hist

    subroutine draw_corr(rng, cm, nv, nf, lf, ld, fs, idio, z)
        type(rng_t), intent(inout) :: rng
        integer, intent(in) :: cm, nv, nf
        real(real64), intent(in) :: lf(:), ld(:), fs(:), idio(:)
        real(real64), intent(out) :: z(:)
        real(real64) :: acc, fac(max(1, nf)), eps(nv)
        integer :: i, j
        if (cm == 1) then
            do j = 1, nf
                fac(j) = rng_normal(rng, 0.0_real64, 1.0_real64) * fs(j)
            end do
            do i = 1, nv
                acc = 0.0_real64
                do j = 1, nf
                    acc = acc + ld((i - 1) * nf + j) * fac(j)
                end do
                z(i) = acc + idio(i) * rng_normal(rng, 0.0_real64, 1.0_real64)
            end do
        else
            do j = 1, nv
                eps(j) = rng_normal(rng, 0.0_real64, 1.0_real64)
            end do
            do i = 1, nv
                acc = 0.0_real64
                do j = 1, i
                    acc = acc + lf((i - 1) * nv + j) * eps(j)
                end do
                z(i) = acc
            end do
        end if
    end subroutine draw_corr

    subroutine ci_pair(b, key, centre, s)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: centre, s
        call kv_raw(b, key); call jb_push(b, '[')
        call jb_f64(b, centre - 1.96_real64 * s); call jb_push(b, ',')
        call jb_f64(b, centre + 1.96_real64 * s); call jb_push(b, ']')
    end subroutine ci_pair

    pure function sd1(v, b) result(s)
        real(real64), intent(in) :: v(:)
        integer, intent(in) :: b
        real(real64) :: s, m, acc
        integer :: i
        if (b < 2) then
            s = 0.0_real64
            return
        end if
        m = sum(v(1:b)) / real(b, real64)
        acc = 0.0_real64
        do i = 1, b
            acc = acc + (v(i) - m) ** 2
        end do
        s = sqrt(acc / real(b - 1, real64)) / sqrt(real(b, real64))
    end function sd1

    subroutine batch_ci(profit, n, se, nb)
        real(real64), intent(in) :: profit(:)
        integer, intent(in) :: n
        real(real64), intent(out) :: se(4)
        integer, intent(out) :: nb
        real(real64), allocatable :: bc(:), vE(:), vV5(:), vV1(:), vC5(:)
        real(real64) :: q5
        integer :: base, rem, bi, lo, sz
        nb = min(40, max(2, n / 500))
        allocate(vE(nb), vV5(nb), vV1(nb), vC5(nb))
        base = n / nb
        rem = n - base * nb
        lo = 1
        do bi = 1, nb
            sz = base
            if (bi <= rem) sz = base + 1
            allocate(bc(sz)); bc = profit(lo:lo + sz - 1)
            call sort_asc(bc, 1, sz)
            vE(bi) = sum(bc) / real(sz, real64)
            q5 = percentile_linear(bc, sz, 5.0_real64)
            vV5(bi) = q5
            vV1(bi) = percentile_linear(bc, sz, 1.0_real64)
            vC5(bi) = tail_mean(bc, sz, q5)
            deallocate(bc)
            lo = lo + sz
        end do
        se(1) = sd1(vE, nb); se(2) = sd1(vV5, nb)
        se(3) = sd1(vV1, nb); se(4) = sd1(vC5, nb)
    end subroutine batch_ci

    pure function cv_of(s, m) result(r)
        real(real64), intent(in) :: s, m
        real(real64) :: r
        if (m /= 0.0_real64) then; r = s / abs(m);
        else; r = 0.0_real64;
        end if
    end function cv_of

    pure function sharpe_of(m, s) result(r)
        real(real64), intent(in) :: m, s
        real(real64) :: r
        if (s /= 0.0_real64) then; r = m / s;
        else; r = 0.0_real64;
        end if
    end function sharpe_of

    pure function rpt_of(m, t) result(r)
        real(real64), intent(in) :: m, t
        real(real64) :: r
        if (t /= 0.0_real64) then; r = m / t;
        else; r = 0.0_real64;
        end if
    end function rpt_of

    function median_of(arr, n) result(r)
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        real(real64) :: r
        real(real64), allocatable :: c(:)
        allocate(c(n)); c = arr(1:n); call sort_asc(c, 1, n)
        r = percentile_linear(c, n, 50.0_real64)
    end function median_of

    function pctl_of(arr, n, q) result(r)
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        real(real64), intent(in) :: q
        real(real64) :: r
        real(real64), allocatable :: c(:)
        allocate(c(n)); c = arr(1:n); call sort_asc(c, 1, n)
        r = percentile_linear(c, n, q)
    end function pctl_of

    ! Monte-Carlo core

    subroutine mc_core(c, rng, profit, time_h, mat_cost, revenue, taxes, logistics)
        type(simctx), intent(in) :: c
        type(rng_t), intent(inout) :: rng
        real(real64), intent(out) :: profit(:), time_h(:), mat_cost(:)
        real(real64), intent(out) :: revenue(:), taxes(:), logistics(:)
        real(real64), allocatable :: z(:), price(:), spr(:)
        real(real64), allocatable :: xpath(:), x_step1(:), sig2(:), prev_eps(:), prev_sig(:)
        real(real64) :: base, fillm, buyp, sellp, vol, exec_cap, u
        real(real64) :: rev_k, mat_k, tax_k, log_k, delay_h, tdf, sscale
        integer :: k, j, off, nv, nl

        nv = c%n_vars; nl = c%n_legs
        allocate(z(nv), price(nv), spr(nv))
        allocate(xpath(nv), x_step1(nv), sig2(nv), prev_eps(nv), prev_sig(nv))

        do k = 1, c%n
            ! Correlated shocks -> prices
            if (c%path_steps > 1) then
                tdf = max(2.5_real64, c%t_df)
                xpath(1:nv) = c%x0(1:nv)
                sig2(1:nv) = c%step_sigma(1:nv) ** 2
                prev_eps(1:nv) = 0.0_real64
                prev_sig(1:nv) = c%step_sigma(1:nv)
                x_step1(1:nv) = c%x0(1:nv)
                do j = 1, c%path_steps
                    call draw_corr(rng, c%corr_mode, nv, c%n_factors, c%l_flat, c%loadings_flat, &
                            c%factor_sigma, c%idio_sigma, z)
                    if (c%copula == 1) then
                        sscale = sqrt(tdf / max(rng_chi2(rng, tdf), 1.0e-12_real64)) &
                                / sqrt(tdf / (tdf - 2.0_real64))
                        z(1:nv) = z(1:nv) * sscale
                    end if
                    call path_step(c, j, nv, z, xpath, sig2, prev_eps, prev_sig)
                    if (j == 1) x_step1(1:nv) = xpath(1:nv)
                end do
                do j = 1, nl
                    price(j) = exp(x_step1(j))
                end do
                price(nv) = exp(xpath(nv))
            else
                call draw_corr(rng, c%corr_mode, nv, c%n_factors, c%l_flat, c%loadings_flat, &
                        c%factor_sigma, c%idio_sigma, z)
                if (c%copula == 1) then
                    tdf = max(2.5_real64, c%t_df)
                    sscale = sqrt(tdf / max(rng_chi2(rng, tdf), 1.0e-12_real64))
                    do j = 1, nv
                        u = student_t_cdf(z(j) * sscale, tdf)
                        off = (j - 1) * GRIDK
                        if (c%dist_mode == 1) then
                            price(j) = exp(c%mu(j) + c%sigma(j) * norm_ppf(u))
                        else
                            price(j) = quantile_grid_interp(c%qgrid_flat(off + 1:off + GRIDK), GRIDK, u)
                        end if
                    end do
                else
                    do j = 1, nv
                        off = (j - 1) * GRIDK
                        if (c%dist_mode == 1) then
                            price(j) = exp(c%mu(j) + c%sigma(j) * z(j))
                        else
                            u = norm_cdf(z(j))
                            price(j) = quantile_grid_interp(c%qgrid_flat(off + 1:off + GRIDK), GRIDK, u)
                        end if
                    end do
                end if
            end if

            ! Spread / execution price
            do j = 1, nv
                spr(j) = c%spread_mean(j) * exp(c%spread_sigma(j) * rng_normal(rng, 0.0_real64, 1.0_real64))
            end do

            ! Liquidity / fill + P&L
            mat_k = 0.0_real64
            do j = 1, nl
                buyp = price(j) * (1.0_real64 + c%slippage * spr(j))
                vol = c%vol_mean(j) * exp(c%vol_sigma(j) * rng_normal(rng, 0.0_real64, 1.0_real64))
                exec_cap = c%participation_cap * vol * c%horizon_days
                if (c%qty(j) > 0.0_real64 .and. c%vol_mean(j) > 0.0_real64) then
                    fillm = min(1.0_real64, exec_cap / c%qty(j))
                else
                    fillm = 1.0_real64
                end if
                base = buyp * c%qty(j)
                mat_k = mat_k + base * (1.0_real64 + (1.0_real64 - fillm) * c%shortfall_premium)
            end do

            sellp = price(nv) * (1.0_real64 - c%slippage * spr(nv))
            rev_k = c%product_qty * sellp
            tax_k = rev_k * (c%broker_fee_pct + c%sales_tax_pct) / 100.0_real64

            delay_h = 0.0_real64
            if (c%haul_delay_prob > 0.0_real64 .and. c%haul_delay_hours_mean > 0.0_real64) then
                if (rng_uniform(rng) < c%haul_delay_prob) then
                    u = rng_uniform(rng)
                    if (u <= 0.0_real64) u = 1.0e-12_real64
                    delay_h = -c%haul_delay_hours_mean * log(u)
                end if
            end if
            log_k = mat_k * c%holding_daily_rate * (delay_h / 24.0_real64)

            mat_cost(k) = mat_k
            revenue(k) = rev_k
            taxes(k) = tax_k
            logistics(k) = log_k
            profit(k) = rev_k - tax_k - mat_k - c%fixed_cost - log_k
            time_h(k) = real(c%production_time_s, real64) / 3600.0_real64 + delay_h
        end do
    end subroutine mc_core

    ! one log-price path step with the martingale
    subroutine path_step(c, tau, nv, z, xpath, sig2, prev_eps, prev_sig)
        type(simctx), intent(in) :: c
        integer, intent(in) :: tau, nv
        real(real64), intent(in) :: z(:)
        real(real64), intent(inout) :: xpath(:), sig2(:), prev_eps(:), prev_sig(:)
        real(real64) :: sg
        integer :: j
        do j = 1, nv
            if (c%garch == 1) then
                if (tau > 1) sig2(j) = c%garch_omega(j) &
                        + c%garch_alpha * (prev_sig(j) * prev_eps(j)) ** 2 + c%garch_beta * sig2(j)
                sg = sqrt(max(sig2(j), 1.0e-300_real64))
            else
                sg = c%step_sigma(j)
            end if
            xpath(j) = xpath(j) + c%ar_phi(j) * (c%theta(j) - xpath(j)) &
                    - 0.5_real64 * sg * sg + sg * z(j)
            prev_eps(j) = z(j)
            prev_sig(j) = sg
        end do
    end subroutine path_step

    ! metric reduction + emit

    subroutine emit_metrics(b, c, profit, time_h, mat_cost, revenue, taxes, logistics)
        type(jbuilder), intent(inout) :: b
        type(simctx), intent(in) :: c
        real(real64), intent(in) :: profit(:), time_h(:), mat_cost(:)
        real(real64), intent(in) :: revenue(:), taxes(:), logistics(:)
        real(real64), allocatable :: psorted(:)
        real(real64) :: mean_p, std_p, p1, p5, p25, p50, p75, p95, p99, cvar5, w1
        real(real64) :: time_mean, prob_loss, se(4), mc_rel_error
        integer :: i, n, ncnt, n_batches
        logical :: conv

        n = c%n
        mean_p = mean_f(profit, n)
        std_p = std_f(profit, n, 0)
        allocate(psorted(n)); psorted = profit(1:n); call sort_asc(psorted, 1, n)
        p1 = percentile_linear(psorted, n, 1.0_real64)
        p5 = percentile_linear(psorted, n, 5.0_real64)
        p25 = percentile_linear(psorted, n, 25.0_real64)
        p50 = percentile_linear(psorted, n, 50.0_real64)
        p75 = percentile_linear(psorted, n, 75.0_real64)
        p95 = percentile_linear(psorted, n, 95.0_real64)
        p99 = percentile_linear(psorted, n, 99.0_real64)
        cvar5 = tail_mean(psorted, n, p5)
        w1 = tail_mean(psorted, n, p1)
        ncnt = 0
        do i = 1, n
            if (psorted(i) < 0.0_real64) then
                ncnt = ncnt + 1
            else
                exit
            end if
        end do
        prob_loss = real(ncnt, real64) / real(n, real64)
        time_mean = mean_f(time_h, n)

        call batch_ci(profit, n, se, n_batches)
        if (mean_p /= 0.0_real64) then
            mc_rel_error = se(1) / abs(mean_p)
            conv = (1.96_real64 * se(1)) < 0.01_real64 * abs(mean_p)
        else
            mc_rel_error = 0.0_real64
            conv = .false.
        end if

        call jb_push(b, '{')
        call kvi(b, 'n_iterations', n);                  call jb_push(b, ',')
        call kvf(b, 'expected_profit', mean_p);          call jb_push(b, ',')
        call kvf(b, 'median_profit', p50);               call jb_push(b, ',')
        call kvf(b, 'std', std_p);                       call jb_push(b, ',')
        call kvf(b, 'cv', cv_of(std_p, mean_p));         call jb_push(b, ',')
        call kvf(b, 'var5', p5);                         call jb_push(b, ',')
        call kvf(b, 'var1', p1);                         call jb_push(b, ',')
        call kvf(b, 'cvar5', cvar5);                     call jb_push(b, ',')
        call kvf(b, 'worst1', w1);                       call jb_push(b, ',')
        call kvf(b, 'prob_loss', prob_loss);             call jb_push(b, ',')
        call kv_raw(b, 'percentiles'); call jb_push(b, '{')
        call kvf(b, 'p1', p1);   call jb_push(b, ',')
        call kvf(b, 'p5', p5);   call jb_push(b, ',')
        call kvf(b, 'p25', p25); call jb_push(b, ',')
        call kvf(b, 'p50', p50); call jb_push(b, ',')
        call kvf(b, 'p75', p75); call jb_push(b, ',')
        call kvf(b, 'p95', p95); call jb_push(b, ',')
        call kvf(b, 'p99', p99)
        call jb_push(b, '},')
        call kvf(b, 'best', psorted(n));                 call jb_push(b, ',')
        call kvf(b, 'worst', psorted(1));                call jb_push(b, ',')
        call emit_hist(b, 'hist_counts', 'hist_edges', profit, n); call jb_push(b, ',')
        call kv_raw(b, 'breakdown'); call jb_push(b, '{')
        call emit_stat(b, 'material_cost', mat_cost, n); call jb_push(b, ',')
        call emit_stat(b, 'revenue', revenue, n);        call jb_push(b, ',')
        call emit_stat(b, 'taxes_fees', taxes, n);       call jb_push(b, ',')
        call emit_stat(b, 'logistics', logistics, n)
        call jb_push(b, '},')
        call kvf(b, 'time_mean_h', time_mean);                       call jb_push(b, ',')
        call kvf(b, 'time_median_h', median_of(time_h, n));          call jb_push(b, ',')
        call kvf(b, 'time_p95_h', pctl_of(time_h, n, 95.0_real64));  call jb_push(b, ',')
        call kvf(b, 'time_per_job_h', real(c%production_time_s, real64) / 3600.0_real64 &
                / real(max(1, c%slots), real64)); call jb_push(b, ',')
        call emit_hist(b, 'time_hist_counts', 'time_hist_edges', time_h, n); call jb_push(b, ',')
        call kvf(b, 'sharpe_like', sharpe_of(mean_p, std_p));        call jb_push(b, ',')
        call kvf(b, 'risk_adjusted', mean_p - c%risk_lambda * std_p); call jb_push(b, ',')
        call kvf(b, 'return_per_slot', mean_p / real(max(1, c%slots), real64)); call jb_push(b, ',')
        call kvf(b, 'return_per_time', rpt_of(mean_p, time_mean));   call jb_push(b, ',')
        call kv_raw(b, 'standard_error'); call jb_push(b, '{')
        call kvf(b, 'expected_profit', se(1)); call jb_push(b, ',')
        call kvf(b, 'var5', se(2)); call jb_push(b, ',')
        call kvf(b, 'var1', se(3)); call jb_push(b, ',')
        call kvf(b, 'cvar5', se(4))
        call jb_push(b, '},')
        call kv_raw(b, 'ci95'); call jb_push(b, '{')
        call ci_pair(b, 'expected_profit', mean_p, se(1)); call jb_push(b, ',')
        call ci_pair(b, 'var5', p5, se(2)); call jb_push(b, ',')
        call ci_pair(b, 'var1', p1, se(3)); call jb_push(b, ',')
        call ci_pair(b, 'cvar5', cvar5, se(4))
        call jb_push(b, '},')
        call kvf(b, 'mc_rel_error', mc_rel_error); call jb_push(b, ',')
        call kv_raw(b, 'converged')
        if (conv) then; call jb_push(b, 'true');
        else; call jb_push(b, 'false');
        end if
        call jb_push(b, ',')
        call kvi(b, 'n_batches', n_batches)
        call jb_push(b, '}')
    end subroutine emit_metrics

    ! decode baseline context

    subroutine decode_ctx(buf, c)
        character(len = *), intent(in) :: buf
        type(simctx), intent(out) :: c
        logical :: f
        integer :: nq

        c%n = get_int_or(buf, 'n', 10000)
        c%corr_mode = get_int_or(buf, 'corr_mode', 0)
        c%dist_mode = get_int_or(buf, 'dist_mode', 0)
        c%n_legs = get_int_or(buf, 'n_legs', 0)
        c%n_vars = get_int_or(buf, 'n_vars', c%n_legs + 1)
        c%n_factors = get_int_or(buf, 'n_factors', 1)
        c%production_time_s = get_int_or(buf, 'production_time_s', 0)
        c%slots = max(1, get_int_or(buf, 'slots', 1))
        c%copula = get_int_or(buf, 'copula', 0)
        c%garch = get_int_or(buf, 'garch', 0)
        c%path_steps = max(1, get_int_or(buf, 'path_steps', 1))
        call get_f64_scalar(buf, 'horizon_days', c%horizon_days, f);           if (.not. f) c%horizon_days = 1.0_real64
        call get_f64_scalar(buf, 'fixed_cost', c%fixed_cost, f);               if (.not. f) c%fixed_cost = 0.0_real64
        call get_f64_scalar(buf, 'participation_cap', c%participation_cap, f); if (.not. f) c%participation_cap = 0.1_real64
        call get_f64_scalar(buf, 'shortfall_premium', c%shortfall_premium, f); if (.not. f) c%shortfall_premium = 0.25_real64
        call get_f64_scalar(buf, 'slippage', c%slippage, f);                   if (.not. f) c%slippage = 0.5_real64
        call get_f64_scalar(buf, 'haul_delay_prob', c%haul_delay_prob, f);     if (.not. f) c%haul_delay_prob = 0.0_real64
        call get_f64_scalar(buf, 'haul_delay_hours_mean', c%haul_delay_hours_mean, f)
        if (.not. f) c%haul_delay_hours_mean = 0.0_real64
        call get_f64_scalar(buf, 'holding_daily_rate', c%holding_daily_rate, f); if (.not. f) c%holding_daily_rate = 0.0_real64
        call get_f64_scalar(buf, 'risk_lambda', c%risk_lambda, f);             if (.not. f) c%risk_lambda = 1.0_real64
        call get_f64_scalar(buf, 'broker_fee_pct', c%broker_fee_pct, f);       if (.not. f) c%broker_fee_pct = 0.0_real64
        call get_f64_scalar(buf, 'sales_tax_pct', c%sales_tax_pct, f);         if (.not. f) c%sales_tax_pct = 0.0_real64
        call get_f64_scalar(buf, 'product_qty', c%product_qty, f);             if (.not. f) c%product_qty = 1.0_real64
        call get_f64_scalar(buf, 't_df', c%t_df, f);                           if (.not. f) c%t_df = 8.0_real64
        call get_f64_scalar(buf, 'garch_alpha', c%garch_alpha, f);             if (.not. f) c%garch_alpha = 0.08_real64
        call get_f64_scalar(buf, 'garch_beta', c%garch_beta, f);               if (.not. f) c%garch_beta = 0.90_real64

        call get_f64_array(buf, 'qty', c%qty, nq)
        call get_f64_array(buf, 'mu', c%mu, nq)
        call get_f64_array(buf, 'sigma', c%sigma, nq)
        call get_f64_array(buf, 'vol_mean', c%vol_mean, nq)
        call get_f64_array(buf, 'vol_sigma', c%vol_sigma, nq)
        call get_f64_array(buf, 'spread_mean', c%spread_mean, nq)
        call get_f64_array(buf, 'spread_sigma', c%spread_sigma, nq)
        call get_f64_array(buf, 'idio_sigma', c%idio_sigma, nq)
        call get_f64_array(buf, 'factor_sigma', c%factor_sigma, nq)
        call get_f64_array(buf, 'qgrid', c%qgrid_flat, nq)
        call get_f64_array(buf, 'l', c%l_flat, nq)
        call get_f64_array(buf, 'loadings', c%loadings_flat, nq)
        call get_f64_array(buf, 'ar_phi', c%ar_phi, nq)
        call get_f64_array(buf, 'step_sigma', c%step_sigma, nq)
        call get_f64_array(buf, 'theta', c%theta, nq)
        call get_f64_array(buf, 'x0', c%x0, nq)
        call get_f64_array(buf, 'garch_omega', c%garch_omega, nq)
    end subroutine decode_ctx


    subroutine apply_mods(b0, m, c1)
        type(simctx), intent(in) :: b0
        real(real64), intent(in) :: m(16)
        type(simctx), intent(out) :: c1
        real(real64) :: matp, prodp, volat, volume, spread, pcost, taxm
        real(real64) :: staxadd, brokadd, sfadd, holdadd, hprob, hhours, timem, slotsm, horizm
        real(real64) :: lm_mat, lm_prod
        integer :: j, off

        c1 = b0
        matp = m(1); prodp = m(2); volat = max(0.0_real64, m(3)); volume = m(4)
        spread = m(5); pcost = m(6); taxm = m(7); staxadd = m(8); brokadd = m(9)
        sfadd = m(10); holdadd = m(11); hprob = m(12); hhours = m(13)
        timem = m(14); slotsm = m(15); horizm = m(16)

        lm_mat = 0.0_real64
        if (matp > 0.0_real64) lm_mat = log(matp)
        lm_prod = 0.0_real64
        if (prodp > 0.0_real64) lm_prod = log(prodp)

        ! legs: material price level + volatility + volume + spread
        do j = 1, b0%n_legs
            c1%mu(j) = b0%mu(j) + lm_mat
            c1%sigma(j) = b0%sigma(j) * volat
            c1%step_sigma(j) = b0%step_sigma(j) * volat
            c1%theta(j) = b0%theta(j) + lm_mat
            c1%x0(j) = b0%x0(j) + lm_mat
            c1%vol_mean(j) = b0%vol_mean(j) * volume
            c1%spread_mean(j) = b0%spread_mean(j) * spread
            c1%garch_omega(j) = b0%garch_omega(j) * volat * volat
            off = (j - 1) * GRIDK
            c1%qgrid_flat(off + 1:off + GRIDK) = b0%qgrid_flat(off + 1:off + GRIDK) * matp
        end do
        ! product: product price level + volatility + volume + spread + fees
        j = b0%n_vars
        c1%mu(j) = b0%mu(j) + lm_prod
        c1%sigma(j) = b0%sigma(j) * volat
        c1%step_sigma(j) = b0%step_sigma(j) * volat
        c1%theta(j) = b0%theta(j) + lm_prod
        c1%x0(j) = b0%x0(j) + lm_prod
        c1%vol_mean(j) = b0%vol_mean(j) * volume
        c1%spread_mean(j) = b0%spread_mean(j) * spread
        c1%garch_omega(j) = b0%garch_omega(j) * volat * volat
        off = (j - 1) * GRIDK
        c1%qgrid_flat(off + 1:off + GRIDK) = b0%qgrid_flat(off + 1:off + GRIDK) * prodp
        c1%broker_fee_pct = b0%broker_fee_pct * taxm + brokadd
        c1%sales_tax_pct = b0%sales_tax_pct * taxm + staxadd

        ! scalars
        c1%fixed_cost = b0%fixed_cost * pcost
        c1%production_time_s = nint(real(b0%production_time_s, real64) * timem)
        c1%slots = max(1, nint(real(b0%slots, real64) * slotsm))
        c1%horizon_days = b0%horizon_days * horizm
        c1%shortfall_premium = max(0.0_real64, b0%shortfall_premium + sfadd)
        c1%holding_daily_rate = max(0.0_real64, b0%holding_daily_rate + holdadd)
        if (hprob >= 0.0_real64) c1%haul_delay_prob = hprob
        if (hhours >= 0.0_real64) c1%haul_delay_hours_mean = hhours
    end subroutine apply_mods

    subroutine get_sc(buf, key, ns, default, arr)
        character(len = *), intent(in) :: buf, key
        integer, intent(in) :: ns
        real(real64), intent(in) :: default
        real(real64), allocatable, intent(out) :: arr(:)
        real(real64), allocatable :: tmp(:)
        integer :: nt, i
        call get_f64_array(buf, key, tmp, nt)
        allocate(arr(max(ns, 1)))
        arr = default
        do i = 1, min(nt, ns)
            arr(i) = tmp(i)
        end do
    end subroutine get_sc

    ! entry point

    function build_scenario_report(buf) result(out)
        character(len = *), intent(in) :: buf
        character(len = :), allocatable :: out
        type(jbuilder) :: b
        type(rng_t) :: rng
        type(simctx) :: c0, c1
        integer :: seed, ns, k, n
        real(real64) :: m(16)
        real(real64), allocatable :: profit(:), time_h(:), mat_cost(:), revenue(:), taxes(:), logistics(:)
        real(real64), allocatable :: s_matp(:), s_prodp(:), s_volat(:), s_volume(:), s_spread(:)
        real(real64), allocatable :: s_pcost(:), s_taxm(:), s_staxadd(:), s_brokadd(:), s_sfadd(:)
        real(real64), allocatable :: s_holdadd(:), s_hprob(:), s_hhours(:), s_timem(:), s_slotsm(:), s_horizm(:)

        call decode_ctx(buf, c0)
        n = c0%n
        if (n < 1 .or. c0%n_vars < 1) then
            out = ''
            return
        end if
        seed = get_int_or(buf, 'seed', 42)
        ns = max(0, get_int_or(buf, 'n_scenarios', 0))

        ! modifier columns
        call get_sc(buf, 'sc_material_price_mult', ns, 1.0_real64, s_matp)
        call get_sc(buf, 'sc_product_price_mult', ns, 1.0_real64, s_prodp)
        call get_sc(buf, 'sc_volatility_mult', ns, 1.0_real64, s_volat)
        call get_sc(buf, 'sc_volume_mult', ns, 1.0_real64, s_volume)
        call get_sc(buf, 'sc_spread_mult', ns, 1.0_real64, s_spread)
        call get_sc(buf, 'sc_production_cost_mult', ns, 1.0_real64, s_pcost)
        call get_sc(buf, 'sc_tax_mult', ns, 1.0_real64, s_taxm)
        call get_sc(buf, 'sc_sales_tax_add', ns, 0.0_real64, s_staxadd)
        call get_sc(buf, 'sc_broker_fee_add', ns, 0.0_real64, s_brokadd)
        call get_sc(buf, 'sc_shortfall_premium_add', ns, 0.0_real64, s_sfadd)
        call get_sc(buf, 'sc_holding_rate_add', ns, 0.0_real64, s_holdadd)
        call get_sc(buf, 'sc_haul_delay_prob', ns, -1.0_real64, s_hprob)
        call get_sc(buf, 'sc_haul_delay_hours_mean', ns, -1.0_real64, s_hhours)
        call get_sc(buf, 'sc_time_mult', ns, 1.0_real64, s_timem)
        call get_sc(buf, 'sc_slots_mult', ns, 1.0_real64, s_slotsm)
        call get_sc(buf, 'sc_horizon_mult', ns, 1.0_real64, s_horizm)

        allocate(profit(n), time_h(n), mat_cost(n), revenue(n), taxes(n), logistics(n))

        call jb_init(b)
        call jb_push(b, '{')
        call kv_raw(b, 'baseline')
        call rng_seed(rng, seed)
        call mc_core(c0, rng, profit, time_h, mat_cost, revenue, taxes, logistics)
        call emit_metrics(b, c0, profit, time_h, mat_cost, revenue, taxes, logistics)
        call jb_push(b, ',')
        call kv_raw(b, 'scenarios'); call jb_push(b, '[')
        do k = 1, ns
            if (k > 1) call jb_push(b, ',')
            m = [s_matp(k), s_prodp(k), s_volat(k), s_volume(k), s_spread(k), s_pcost(k), &
                    s_taxm(k), s_staxadd(k), s_brokadd(k), s_sfadd(k), s_holdadd(k), s_hprob(k), &
                    s_hhours(k), s_timem(k), s_slotsm(k), s_horizm(k)]
            call apply_mods(c0, m, c1)
            call rng_seed(rng, seed)
            call mc_core(c1, rng, profit, time_h, mat_cost, revenue, taxes, logistics)
            call emit_metrics(b, c1, profit, time_h, mat_cost, revenue, taxes, logistics)
        end do
        call jb_push(b, ']')
        call jb_push(b, '}')
        out = jb_str(b)
    end function build_scenario_report

end module scenario_mod
