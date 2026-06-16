! Monte-Carlo profit simulator — the native compute core (profit-sim binary).

module montecarlo_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use json_mod
    use sort_stats_mod, only : sort_asc, percentile_linear, mean_f, std_f, histogram_np
    use rng_mod, only : rng_t, rng_seed, rng_uniform, rng_normal, rng_chi2
    use distrib_mod, only : norm_cdf, norm_ppf, student_t_cdf, quantile_grid_interp
    implicit none
    private
    public :: build_sim_report

    integer, parameter :: GRIDK = 101
    integer, parameter :: NBINS = 40

contains

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
        call kvf(b, 'mean', mean_f(arr, n));                 call jb_push(b, ',')
        call kvf(b, 'p5', percentile_linear(c, n, 5.0_real64));  call jb_push(b, ',')
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

    ! Correlated standard normals z(nv): Cholesky (cm=0) or factor model (cm=1).
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
            do i = 1, nv                              ! z = L·eps (L lower-triangular)
                acc = 0.0_real64
                do j = 1, i
                    acc = acc + lf((i - 1) * nv + j) * eps(j)
                end do
                z(i) = acc
            end do
        end if
    end subroutine draw_corr

    ! "key":[centre−1.96σ, centre+1.96σ]
    subroutine ci_pair(b, key, centre, s)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        real(real64), intent(in) :: centre, s
        call kv_raw(b, key); call jb_push(b, '[')
        call jb_f64(b, centre - 1.96_real64 * s); call jb_push(b, ',')
        call jb_f64(b, centre + 1.96_real64 * s); call jb_push(b, ']')
    end subroutine ci_pair

    ! batch standard error: std(batch metrics, ddof=1) / √B
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

    ! Batch-means MC standard errors for {E, VaR5, VaR1, CVaR5} (contiguous i.i.d.
    ! batches, array-split style: first `rem` batches get one extra sample).
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

    ! the simulation

    function build_sim_report(buf) result(out)
        character(len = *), intent(in) :: buf
        character(len = :), allocatable :: out
        type(jbuilder) :: b
        type(rng_t) :: rng

        ! scalars
        integer :: n, seed, corr_mode, dist_mode, n_legs, n_vars, n_factors
        integer :: production_time_s, slots, copula, garch, path_steps, tau, n_batches
        real(real64) :: horizon_days, fixed_cost, participation_cap, shortfall_premium
        real(real64) :: slippage, haul_delay_prob, haul_delay_hours_mean, holding_daily_rate
        real(real64) :: risk_lambda, broker_fee_pct, sales_tax_pct, product_qty
        real(real64) :: t_df, garch_alpha, garch_beta, tdf, sscale, sg, mc_rel_error
        logical :: f, conv

        ! arrays (per-variable; var order = legs…, product last)
        real(real64), allocatable :: qty(:), mu(:), sigma(:), vol_mean(:), vol_sigma(:)
        real(real64), allocatable :: spread_mean(:), spread_sigma(:), idio_sigma(:)
        real(real64), allocatable :: factor_sigma(:), qgrid_flat(:), l_flat(:), loadings_flat(:)
        real(real64), allocatable :: ar_phi(:), step_sigma(:), theta(:), x0(:), garch_omega(:)
        integer :: nq

        ! per-scenario state
        real(real64), allocatable :: profit(:), time_h(:), mat_cost(:), revenue(:)
        real(real64), allocatable :: taxes(:), logistics(:)
        real(real64), allocatable :: z(:), price(:), spr(:)
        real(real64), allocatable :: xpath(:), x_step1(:), sig2(:), prev_eps(:), prev_sig(:)
        real(real64), allocatable :: psorted(:)
        real(real64) :: base, fillm, buyp, sellp, vol, exec_cap, u
        real(real64) :: rev_k, mat_k, tax_k, log_k, delay_h, se(4)
        real(real64) :: mean_p, std_p, p1, p5, p25, p50, p75, p95, p99, cvar5, w1
        real(real64) :: time_mean, prob_loss
        integer :: k, i, j, off, ncnt

        ! decode scalars
        n = get_int_or(buf, 'n', 10000)
        seed = get_int_or(buf, 'seed', 42)
        corr_mode = get_int_or(buf, 'corr_mode', 0)
        dist_mode = get_int_or(buf, 'dist_mode', 0)
        n_legs = get_int_or(buf, 'n_legs', 0)
        n_vars = get_int_or(buf, 'n_vars', n_legs + 1)
        n_factors = get_int_or(buf, 'n_factors', 1)
        production_time_s = get_int_or(buf, 'production_time_s', 0)
        slots = max(1, get_int_or(buf, 'slots', 1))
        call get_f64_scalar(buf, 'horizon_days', horizon_days, f);            if (.not. f) horizon_days = 1.0_real64
        call get_f64_scalar(buf, 'fixed_cost', fixed_cost, f);                if (.not. f) fixed_cost = 0.0_real64
        call get_f64_scalar(buf, 'participation_cap', participation_cap, f);  if (.not. f) participation_cap = 0.1_real64
        call get_f64_scalar(buf, 'shortfall_premium', shortfall_premium, f);  if (.not. f) shortfall_premium = 0.25_real64
        call get_f64_scalar(buf, 'slippage', slippage, f);                    if (.not. f) slippage = 0.5_real64
        call get_f64_scalar(buf, 'haul_delay_prob', haul_delay_prob, f);      if (.not. f) haul_delay_prob = 0.0_real64
        call get_f64_scalar(buf, 'haul_delay_hours_mean', haul_delay_hours_mean, f); if (.not. f) haul_delay_hours_mean = 0.0_real64
        call get_f64_scalar(buf, 'holding_daily_rate', holding_daily_rate, f);if (.not. f) holding_daily_rate = 0.0_real64
        call get_f64_scalar(buf, 'risk_lambda', risk_lambda, f);              if (.not. f) risk_lambda = 1.0_real64
        call get_f64_scalar(buf, 'broker_fee_pct', broker_fee_pct, f);        if (.not. f) broker_fee_pct = 0.0_real64
        call get_f64_scalar(buf, 'sales_tax_pct', sales_tax_pct, f);          if (.not. f) sales_tax_pct = 0.0_real64
        call get_f64_scalar(buf, 'product_qty', product_qty, f);              if (.not. f) product_qty = 1.0_real64
        ! IO-22 hardening: copula / path-dynamics controls
        copula = get_int_or(buf, 'copula', 0)
        garch = get_int_or(buf, 'garch', 0)
        path_steps = max(1, get_int_or(buf, 'path_steps', 1))
        call get_f64_scalar(buf, 't_df', t_df, f);            if (.not. f) t_df = 8.0_real64
        call get_f64_scalar(buf, 'garch_alpha', garch_alpha, f); if (.not. f) garch_alpha = 0.08_real64
        call get_f64_scalar(buf, 'garch_beta', garch_beta, f);   if (.not. f) garch_beta = 0.90_real64

        if (n < 1 .or. n_vars < 1) then
            out = ''
            return
        end if

        ! decode arrays
        call get_f64_array(buf, 'qty', qty, nq)
        call get_f64_array(buf, 'mu', mu, nq)
        call get_f64_array(buf, 'sigma', sigma, nq)
        call get_f64_array(buf, 'vol_mean', vol_mean, nq)
        call get_f64_array(buf, 'vol_sigma', vol_sigma, nq)
        call get_f64_array(buf, 'spread_mean', spread_mean, nq)
        call get_f64_array(buf, 'spread_sigma', spread_sigma, nq)
        call get_f64_array(buf, 'idio_sigma', idio_sigma, nq)
        call get_f64_array(buf, 'factor_sigma', factor_sigma, nq)
        call get_f64_array(buf, 'qgrid', qgrid_flat, nq)
        call get_f64_array(buf, 'l', l_flat, nq)
        call get_f64_array(buf, 'loadings', loadings_flat, nq)
        call get_f64_array(buf, 'ar_phi', ar_phi, nq)
        call get_f64_array(buf, 'step_sigma', step_sigma, nq)
        call get_f64_array(buf, 'theta', theta, nq)
        call get_f64_array(buf, 'x0', x0, nq)
        call get_f64_array(buf, 'garch_omega', garch_omega, nq)

        allocate(profit(n), time_h(n), mat_cost(n), revenue(n), taxes(n), logistics(n))
        allocate(z(n_vars), price(n_vars), spr(n_vars))
        allocate(xpath(n_vars), x_step1(n_vars), sig2(n_vars), prev_eps(n_vars), prev_sig(n_vars))

        call rng_seed(rng, seed)

        do k = 1, n
            ! 1+2. correlated shocks → prices: AR(1)/OU(+GARCH) path, or one-shot
            ! (Gaussian or Student-t copula) terminal draw.
            if (path_steps > 1) then
                tdf = max(2.5_real64, t_df)
                xpath(1:n_vars) = x0(1:n_vars)
                sig2(1:n_vars) = step_sigma(1:n_vars) ** 2
                prev_eps(1:n_vars) = 0.0_real64
                prev_sig(1:n_vars) = step_sigma(1:n_vars)
                x_step1(1:n_vars) = x0(1:n_vars)
                do tau = 1, path_steps
                    call draw_corr(rng, corr_mode, n_vars, n_factors, l_flat, loadings_flat, &
                            factor_sigma, idio_sigma, z)
                    if (copula == 1) then
                        sscale = sqrt(tdf / max(rng_chi2(rng, tdf), 1.0e-12_real64)) &
                                / sqrt(tdf / (tdf - 2.0_real64))
                        do j = 1, n_vars
                            z(j) = z(j) * sscale
                        end do
                    end if
                    do j = 1, n_vars
                        if (garch == 1) then
                            if (tau > 1) sig2(j) = garch_omega(j) &
                                    + garch_alpha * (prev_sig(j) * prev_eps(j)) ** 2 + garch_beta * sig2(j)
                            sg = sqrt(max(sig2(j), 1.0e-300_real64))
                        else
                            sg = step_sigma(j)
                        end if
                        xpath(j) = xpath(j) + ar_phi(j) * (theta(j) - xpath(j)) + sg * z(j)
                        prev_eps(j) = z(j)
                        prev_sig(j) = sg
                    end do
                    if (tau == 1) x_step1(1:n_vars) = xpath(1:n_vars)
                end do
                do j = 1, n_legs                     ! legs bought at step 1
                    price(j) = exp(x_step1(j))
                end do
                price(n_vars) = exp(xpath(n_vars))   ! product sold at terminal step H
            else
                call draw_corr(rng, corr_mode, n_vars, n_factors, l_flat, loadings_flat, &
                        factor_sigma, idio_sigma, z)
                if (copula == 1) then                ! Student-t copula (tail dependence)
                    tdf = max(2.5_real64, t_df)
                    sscale = sqrt(tdf / max(rng_chi2(rng, tdf), 1.0e-12_real64))
                    do j = 1, n_vars
                        u = student_t_cdf(z(j) * sscale, tdf)
                        if (dist_mode == 1) then
                            price(j) = exp(mu(j) + sigma(j) * norm_ppf(u))
                        else
                            off = (j - 1) * GRIDK
                            price(j) = quantile_grid_interp(qgrid_flat(off + 1:off + GRIDK), GRIDK, u)
                        end if
                    end do
                else                                 ! Gaussian copula (default)
                    do j = 1, n_vars
                        if (dist_mode == 1) then
                            price(j) = exp(mu(j) + sigma(j) * z(j))
                        else
                            u = norm_cdf(z(j))
                            off = (j - 1) * GRIDK
                            price(j) = quantile_grid_interp(qgrid_flat(off + 1:off + GRIDK), GRIDK, u)
                        end if
                    end do
                end if
            end if

            ! 3. spread / execution price
            do j = 1, n_vars
                spr(j) = spread_mean(j) * exp(spread_sigma(j) * rng_normal(rng, 0.0_real64, 1.0_real64))
            end do

            ! 4. liquidity / fill + 5. P&L
            mat_k = 0.0_real64
            do j = 1, n_legs
                buyp = price(j) * (1.0_real64 + slippage * spr(j))
                vol = vol_mean(j) * exp(vol_sigma(j) * rng_normal(rng, 0.0_real64, 1.0_real64))
                exec_cap = participation_cap * vol * horizon_days
                ! No volume history (vol_mean<=0) ⇒ no liquidity constraint (fill=1),
                ! not "unsellable" (fill=0). See the oracle for the rationale.
                if (qty(j) > 0.0_real64 .and. vol_mean(j) > 0.0_real64) then
                    fillm = min(1.0_real64, exec_cap / qty(j))
                else
                    fillm = 1.0_real64
                end if
                base = buyp * qty(j)
                mat_k = mat_k + base * (1.0_real64 + (1.0_real64 - fillm) * shortfall_premium)
            end do

            ! product (last variable). The product sells in FULL — thin product
            ! liquidity means the batch takes longer to sell (price risk over the
            ! horizon, already modelled), it does NOT forfeit units. The old
            ! ``* fillp`` kept only the fraction sellable in one horizon and threw the
            ! rest away, so a low-volume capital lost most of its revenue and a
            ! profitable build read as a near-certain loss. Materials keep their
            ! fill-based shortfall premium above.
            sellp = price(n_vars) * (1.0_real64 - slippage * spr(n_vars))
            rev_k = product_qty * sellp
            tax_k = rev_k * (broker_fee_pct + sales_tax_pct) / 100.0_real64

            ! logistics delay
            delay_h = 0.0_real64
            if (haul_delay_prob > 0.0_real64 .and. haul_delay_hours_mean > 0.0_real64) then
                if (rng_uniform(rng) < haul_delay_prob) then
                    u = rng_uniform(rng)
                    if (u <= 0.0_real64) u = 1.0e-12_real64
                    delay_h = -haul_delay_hours_mean * log(u)        ! Exponential(mean)
                end if
            end if
            log_k = mat_k * holding_daily_rate * (delay_h / 24.0_real64)

            mat_cost(k) = mat_k
            revenue(k) = rev_k
            taxes(k) = tax_k
            logistics(k) = log_k
            profit(k) = rev_k - tax_k - mat_k - fixed_cost - log_k
            time_h(k) = real(production_time_s, real64) / 3600.0_real64 + delay_h
        end do

        ! metrics
        mean_p = mean_f(profit, n)
        std_p = std_f(profit, n, 0)                 ! ddof=0, like the oracle's MC sigma
        allocate(psorted(n)); psorted = profit; call sort_asc(psorted, 1, n)
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

        ! batch-means MC standard errors + convergence
        call batch_ci(profit, n, se, n_batches)
        if (mean_p /= 0.0_real64) then
            mc_rel_error = se(1) / abs(mean_p)
            conv = (1.96_real64 * se(1)) < 0.01_real64 * abs(mean_p)
        else
            mc_rel_error = 0.0_real64
            conv = .false.
        end if

        ! emit
        call jb_init(b)
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
        call kvf(b, 'time_per_job_h', real(production_time_s, real64) / 3600.0_real64 / real(slots, real64)); call jb_push(b, ',')
        call emit_hist(b, 'time_hist_counts', 'time_hist_edges', time_h, n); call jb_push(b, ',')
        call kvf(b, 'sharpe_like', sharpe_of(mean_p, std_p));        call jb_push(b, ',')
        call kvf(b, 'risk_adjusted', mean_p - risk_lambda * std_p);  call jb_push(b, ',')
        call kvf(b, 'return_per_slot', mean_p / real(slots, real64));call jb_push(b, ',')
        call kvf(b, 'return_per_time', rpt_of(mean_p, time_mean));    call jb_push(b, ',')
        ! MC sampling error (batch means)
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
        out = jb_str(b)
    end function build_sim_report

    ! ── guarded scalar helpers (match the oracle's 0-guards) ──

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

end module montecarlo_mod
