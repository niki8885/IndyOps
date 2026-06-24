! Forecast panel - native port of services/forecast.py

module forecast_panel_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_is_nan, ieee_is_finite
    use json_mod
    use sort_stats_mod, only : mean_f, std_f
    use forecast_mod, only : sarima_fit_t, f_sarima
    implicit none
    private
    public :: forecast_one_json

    integer, parameter :: NGRID = 5
    real(real64), parameter :: GRID(NGRID) = (/ 0.1_real64, 0.3_real64, 0.5_real64, &
            0.7_real64, 0.9_real64 /)
    real(real64), parameter :: Z80 = 1.2815515594465777_real64
    integer, parameter :: FOLDS = 4
    integer, parameter :: AR_P = 7
    integer, parameter :: M_SNAIVE = 1, M_HOLT = 2, M_HW = 3, M_CROSTON = 4, &
            M_AR = 5, M_SARIMA = 6

contains

    function model_name(mid) result(nm)
        integer, intent(in) :: mid
        character(len = :), allocatable :: nm
        select case (mid)
        case (M_SNAIVE); nm = 'seasonal_naive'
        case (M_HOLT); nm = 'holt'
        case (M_HW); nm = 'holt_winters'
        case (M_CROSTON); nm = 'croston'
        case (M_AR); nm = 'arima'
        case (M_SARIMA); nm = 'sarima'
        case default; nm = '?'
        end select
    end function model_name

    ! individual models (fc(1:h) from y(1:n))

    subroutine f_snaive(y, n, h, m, fc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, h, m
        real(real64), intent(out) :: fc(:)
        integer :: i
        if (n == 0) then; fc(1:h) = 0.0_real64; return;
        end if
        if (n < m) then; fc(1:h) = y(n); return;
        end if
        do i = 0, h - 1
            fc(i + 1) = y(n - m + mod(i, m) + 1)
        end do
    end subroutine f_snaive

    subroutine holt_run(y, n, alpha, beta, sse, lvl, tr)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n
        real(real64), intent(in) :: alpha, beta
        real(real64), intent(out) :: sse, lvl, tr
        real(real64) :: fitted, prev
        integer :: t
        lvl = y(1)
        tr = 0.0_real64; if (n > 1) tr = y(2) - y(1)
        sse = 0.0_real64
        do t = 1, n - 1
            fitted = lvl + tr
            sse = sse + (y(t + 1) - fitted) ** 2
            prev = lvl
            lvl = alpha * y(t + 1) + (1.0_real64 - alpha) * (lvl + tr)
            tr = beta * (lvl - prev) + (1.0_real64 - beta) * tr
        end do
    end subroutine holt_run

    subroutine f_holt(y, n, h, fc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, h
        real(real64), intent(out) :: fc(:)
        real(real64) :: sse, lvl, tr, bsse, blvl, btr
        integer :: ia, ib, i
        if (n < 3) then; call f_snaive(y, n, h, 7, fc); return;
        end if
        bsse = -1.0_real64; blvl = y(n); btr = 0.0_real64
        do ia = 1, NGRID
            do ib = 1, NGRID
                call holt_run(y, n, GRID(ia), GRID(ib), sse, lvl, tr)
                if (bsse < 0.0_real64 .or. sse < bsse) then
                    bsse = sse; blvl = lvl; btr = tr
                end if
            end do
        end do
        do i = 1, h; fc(i) = blvl + real(i, real64) * btr;
        end do
    end subroutine f_holt

    subroutine hw_run(y, n, alpha, beta, gamma, m, sse, lvl, tr, season)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, m
        real(real64), intent(in) :: alpha, beta, gamma
        real(real64), intent(out) :: sse, lvl, tr, season(:)
        real(real64) :: s, fitted, prev
        integer :: t, jm
        lvl = mean_f(y(1:m), m)
        tr = (mean_f(y(m + 1:2 * m), m) - lvl) / real(m, real64)
        do t = 1, m; season(t) = y(t) - lvl;
        end do
        sse = 0.0_real64
        do t = m, n - 1
            jm = mod(t, m)
            s = season(jm + 1)
            fitted = lvl + tr + s
            sse = sse + (y(t + 1) - fitted) ** 2
            prev = lvl
            lvl = alpha * (y(t + 1) - s) + (1.0_real64 - alpha) * (lvl + tr)
            tr = beta * (lvl - prev) + (1.0_real64 - beta) * tr
            season(jm + 1) = gamma * (y(t + 1) - lvl) + (1.0_real64 - gamma) * s
        end do
    end subroutine hw_run

    subroutine f_hw(y, n, h, m, fc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, h, m
        real(real64), intent(out) :: fc(:)
        real(real64) :: season(m), bseason(m)
        real(real64) :: sse, lvl, tr, bsse, blvl, btr
        integer :: ia, ib, ig, i
        if (n < 2 * m) then; call f_holt(y, n, h, fc); return;
        end if
        bsse = -1.0_real64; blvl = y(n); btr = 0.0_real64; bseason = 0.0_real64
        do ia = 1, NGRID
            do ib = 1, NGRID
                do ig = 1, NGRID
                    call hw_run(y, n, GRID(ia), GRID(ib), GRID(ig), m, sse, lvl, tr, season)
                    if (bsse < 0.0_real64 .or. sse < bsse) then
                        bsse = sse; blvl = lvl; btr = tr; bseason = season
                    end if
                end do
            end do
        end do
        do i = 0, h - 1
            fc(i + 1) = blvl + real(i + 1, real64) * btr + bseason(mod(n + i, m) + 1)
        end do
    end subroutine f_hw

    subroutine f_croston(y, n, h, fc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, h
        real(real64), intent(out) :: fc(:)
        real(real64), parameter :: alpha = 0.1_real64
        real(real64) :: z, p, rate
        integer :: i0, t, q
        i0 = 0
        do t = 1, n
            if (y(t) > 0.0_real64) then; i0 = t; exit;
            end if
        end do
        if (i0 == 0) then; fc(1:h) = 0.0_real64; return;
        end if
        z = y(i0); p = 1.0_real64; q = 1
        do t = i0 + 1, n
            if (y(t) > 0.0_real64) then
                z = alpha * y(t) + (1.0_real64 - alpha) * z
                p = alpha * real(q, real64) + (1.0_real64 - alpha) * p
                q = 1
            else
                q = q + 1
            end if
        end do
        rate = 0.0_real64; if (p /= 0.0_real64) rate = z / p
        fc(1:h) = rate
    end subroutine f_croston

    subroutine gauss_solve(A, b, n, x, ok)
        real(real64), intent(inout) :: A(:, :), b(:)
        integer, intent(in) :: n
        real(real64), intent(out) :: x(:)
        logical, intent(out) :: ok
        integer :: i, j, k, piv
        real(real64) :: mx, factor, tmp
        ok = .true.
        do k = 1, n
            piv = k; mx = abs(A(k, k))
            do i = k + 1, n
                if (abs(A(i, k)) > mx) then; mx = abs(A(i, k)); piv = i;
                end if
            end do
            if (mx < 1.0e-14_real64) then; ok = .false.; return;
            end if
            if (piv /= k) then
                do j = 1, n; tmp = A(k, j); A(k, j) = A(piv, j); A(piv, j) = tmp;
                end do
                tmp = b(k); b(k) = b(piv); b(piv) = tmp
            end if
            do i = k + 1, n
                factor = A(i, k) / A(k, k)
                do j = k, n; A(i, j) = A(i, j) - factor * A(k, j);
                end do
                b(i) = b(i) - factor * b(k)
            end do
        end do
        do i = n, 1, -1
            tmp = b(i)
            do j = i + 1, n; tmp = tmp - A(i, j) * x(j);
            end do
            x(i) = tmp / A(i, i)
        end do
    end subroutine gauss_solve

    subroutine f_ar(y, n, h, fc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, h
        real(real64), intent(out) :: fc(:)
        integer, parameter :: p = AR_P, d = 1
        real(real64), allocatable :: z(:), XtX(:, :), Xty(:), coef(:), hist(:)
        real(real64) :: nxt, acc
        integer :: nz, rows, r, i, j, k, ncol
        logical :: ok
        if (n < p + d + 3) then; call f_holt(y, n, h, fc); return;
        end if
        nz = n - 1; allocate(z(nz))
        do i = 1, nz; z(i) = y(i + 1) - y(i);
        end do
        if (nz <= p + 1) then; call f_holt(y, n, h, fc); return;
        end if
        rows = nz - p; ncol = p + 1
        allocate(XtX(ncol, ncol), Xty(ncol), coef(ncol)); XtX = 0.0_real64; Xty = 0.0_real64
        block
            real(real64) :: xr(ncol)
            do r = 1, rows
                xr(1) = 1.0_real64
                do k = 1, p; xr(k + 1) = z(p - k + r);
                end do
                do i = 1, ncol
                    do j = 1, ncol; XtX(i, j) = XtX(i, j) + xr(i) * xr(j);
                    end do
                    Xty(i) = Xty(i) + xr(i) * z(p + r)
                end do
            end do
        end block
        call gauss_solve(XtX, Xty, ncol, coef, ok)
        if (.not. ok) then; call f_holt(y, n, h, fc); return;
        end if
        allocate(hist(p + h)); hist(1:p) = z(nz - p + 1:nz)
        do i = 1, h
            nxt = coef(1)
            do k = 0, p - 1
                nxt = nxt + coef(k + 2) * hist(p + i - 1 - k)
            end do
            hist(p + i) = nxt
        end do
        acc = 0.0_real64
        do i = 1, h
            acc = acc + hist(p + i)
            fc(i) = y(n) + acc
        end do
    end subroutine f_ar

    subroutine model_fc(mid, y, n, h, m, fc)
        integer, intent(in) :: mid, n, h, m
        real(real64), intent(in) :: y(:)
        real(real64), intent(out) :: fc(:)
        logical :: ok
        select case (mid)
        case (M_SNAIVE); call f_snaive(y, n, h, m, fc)
        case (M_HOLT); call f_holt(y, n, h, fc)
        case (M_HW); call f_hw(y, n, h, m, fc)
        case (M_CROSTON); call f_croston(y, n, h, fc)
        case (M_AR); call f_ar(y, n, h, fc)
        case (M_SARIMA)
            call f_sarima(y, n, h, m, fc, ok)
            if (.not. ok) call f_holt(y, n, h, fc)
        end select
    end subroutine model_fc

    function mase_scale(y, n, m) result(sc)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: n, m
        real(real64) :: sc
        integer :: i
        sc = 0.0_real64
        if (n <= m) then; sc = -1.0_real64; return;
        end if
        do i = 1, n - m; sc = sc + abs(y(i + m) - y(i));
        end do
        sc = sc / real(n - m, real64)
        if (sc <= 0.0_real64) sc = -1.0_real64
    end function mase_scale

    ! walk-forward backtest of one model
    subroutine backtest(mid, y, n, h, m, mase, mape, smape, rmse, diracc, sigstep, hasfolds)
        integer, intent(in) :: mid, n, h, m
        real(real64), intent(in) :: y(:)
        real(real64), intent(out) :: mase, mape, smape, rmse, diracc, sigstep(:)
        logical, intent(out) :: hasfolds
        real(real64) :: fc(h), rstep(h, FOLDS), errsum2, maesum, mapesum, smsum, sc
        real(real64) :: ov_mean, ov_sig, e, denom, sgf, sga
        integer :: scount(h), kf, cut, i, mtrain, nall, mapen, smn, diracc_n
        integer :: rc(h)
        mtrain = max(2 * m, 10)
        scount = 0; rc = 0
        errsum2 = 0.0_real64; maesum = 0.0_real64; mapesum = 0.0_real64; smsum = 0.0_real64
        nall = 0; mapen = 0; smn = 0; diracc_n = 0
        ov_mean = 0.0_real64
        hasfolds = .false.
        do kf = 1, FOLDS
            cut = n - kf * h
            if (cut < mtrain) exit
            hasfolds = .true.
            call model_fc(mid, y(1:cut), cut, h, m, fc)
            do i = 1, h
                if (cut + i > n) exit
                e = fc(i) - y(cut + i)
                rc(i) = rc(i) + 1; rstep(i, rc(i)) = e
                errsum2 = errsum2 + e * e; maesum = maesum + abs(e)
                ov_mean = ov_mean + e; nall = nall + 1
                if (y(cut + i) /= 0.0_real64) then
                    mapesum = mapesum + abs(e / y(cut + i)); mapen = mapen + 1
                end if
                denom = abs(fc(i)) + abs(y(cut + i))
                if (denom /= 0.0_real64) then
                    smsum = smsum + 2.0_real64 * abs(e) / denom; smn = smn + 1
                end if
                sgf = sign(1.0_real64, fc(i)); if (fc(i) == 0.0_real64) sgf = 0.0_real64
                sga = sign(1.0_real64, y(cut + i)); if (y(cut + i) == 0.0_real64) sga = 0.0_real64
                if (sgf == sga) diracc_n = diracc_n + 1
            end do
        end do
        if (.not. hasfolds .or. nall == 0) then
            mase = nan64(); mape = nan64(); smape = nan64(); rmse = nan64(); diracc = nan64()
            sigstep(1:h) = nan64(); return
        end if
        ov_mean = ov_mean / real(nall, real64)
        ov_sig = 0.0_real64
        do kf = 1, FOLDS; end do
        ov_sig = 0.0_real64
        block
            integer :: ii, jj
            do ii = 1, h
                do jj = 1, rc(ii); ov_sig = ov_sig + (rstep(ii, jj) - ov_mean) ** 2;
                end do
            end do
            ov_sig = sqrt(ov_sig / real(nall, real64))
        end block
        sc = mase_scale(y, n, m)
        maesum = maesum / real(nall, real64)
        if (sc > 0.0_real64) then; mase = maesum / sc;
        else; mase = nan64();
        end if
        if (mapen > 0) then; mape = mapesum / real(mapen, real64);
        else; mape = nan64();
        end if
        if (smn > 0) then; smape = smsum / real(smn, real64);
        else; smape = nan64();
        end if
        rmse = sqrt(errsum2 / real(nall, real64))
        diracc = real(diracc_n, real64) / real(nall, real64)

        block
            integer :: ii, jj
            real(real64) :: mu, acc2
            do ii = 1, h
                if (rc(ii) >= 2) then
                    mu = 0.0_real64
                    do jj = 1, rc(ii); mu = mu + rstep(ii, jj);
                    end do
                    mu = mu / real(rc(ii), real64)
                    acc2 = 0.0_real64
                    do jj = 1, rc(ii); acc2 = acc2 + (rstep(ii, jj) - mu) ** 2;
                    end do
                    sigstep(ii) = sqrt(acc2 / real(rc(ii), real64))
                else
                    sigstep(ii) = ov_sig
                end if
            end do
        end block
    end subroutine backtest

    ! emit one target sub-payload
    subroutine forecast_one_json(b, key, panel, npanel, y, n, h, m, is_vol)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: key
        integer, intent(in) :: panel(:), npanel, n, h, m
        real(real64), intent(in) :: y(:)
        logical, intent(in) :: is_vol
        real(real64) :: cmase(npanel), cmape(npanel)
        real(real64) :: mase, mape, smape, rmse, diracc, sigstep(h)
        real(real64) :: bmase, bmape, bsmape, brmse, bdiracc, bsig(h)
        real(real64) :: p50(h), p10(h), p90(h), key_v, best_key
        logical :: hasfolds
        integer :: c, best_c, i

        best_c = 1; best_key = huge(1.0_real64)
        bmase = nan64(); bmape = nan64(); bsmape = nan64(); brmse = nan64(); bdiracc = nan64()
        bsig = nan64()
        do c = 1, npanel
            call backtest(panel(c), y, n, h, m, mase, mape, smape, rmse, diracc, sigstep, hasfolds)
            cmase(c) = mase; cmape(c) = mape
            key_v = mase
            if (ieee_is_nan(key_v)) key_v = huge(1.0_real64)
            if (key_v < best_key) then
                best_key = key_v; best_c = c
                bmase = mase; bmape = mape; bsmape = smape; brmse = rmse; bdiracc = diracc
                bsig = sigstep
            end if
        end do

        call model_fc(panel(best_c), y, n, h, m, p50)
        do i = 1, h
            if (ieee_is_nan(bsig(i))) bsig(i) = std_f(y(1:n), n, 0)
            p10(i) = p50(i) - Z80 * bsig(i)
            p90(i) = p50(i) + Z80 * bsig(i)
        end do
        if (is_vol) then
            do i = 1, h
                if (p50(i) < 0.0_real64) p50(i) = 0.0_real64
                if (p10(i) < 0.0_real64) p10(i) = 0.0_real64
                if (p90(i) < 0.0_real64) p90(i) = 0.0_real64
            end do
        end if

        call jb_push(b, '"'); call jb_push(b, key); call jb_push(b, '":{')
        call jb_push(b, '"model":"'); call jb_push(b, model_name(panel(best_c))); call jb_push(b, '",')
        call jb_push(b, '"p50":'); call jb_f64_array(b, p50, h); call jb_push(b, ',')
        call jb_push(b, '"p10":'); call jb_f64_array(b, p10, h); call jb_push(b, ',')
        call jb_push(b, '"p90":'); call jb_f64_array(b, p90, h); call jb_push(b, ',')
        call jb_push(b, '"backtest":{')
        call jb_push(b, '"mase":'); call jb_f64(b, bmase); call jb_push(b, ',')
        call jb_push(b, '"mape":'); call jb_f64(b, bmape); call jb_push(b, ',')
        call jb_push(b, '"smape":'); call jb_f64(b, bsmape); call jb_push(b, ',')
        call jb_push(b, '"rmse":'); call jb_f64(b, brmse); call jb_push(b, ',')
        call jb_push(b, '"dir_acc":'); call jb_f64(b, bdiracc); call jb_push(b, '},')
        call jb_push(b, '"candidates":[')
        do c = 1, npanel
            if (c > 1) call jb_push(b, ',')
            call jb_push(b, '{"model":"'); call jb_push(b, model_name(panel(c)))
            call jb_push(b, '","mase":'); call jb_f64(b, cmase(c))
            call jb_push(b, ',"mape":'); call jb_f64(b, cmape(c)); call jb_push(b, '}')
        end do
        call jb_push(b, ']}')
    end subroutine forecast_one_json

end module forecast_panel_mod
