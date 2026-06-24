! Native SARIMA(p,d,q)(P,D,Q)_s forecasting core


module forecast_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_is_finite
    implicit none
    private
    public :: sarima_fit_t, sarima_fit, sarima_forecast, auto_select, f_sarima

    type :: sarima_fit_t
        integer :: p = 0, d = 0, q = 0, sp = 0, sd = 0, sq = 0, s = 7
        integer :: naf = 1, nmf = 1, nw = 0, nparam = 0
        real(real64), allocatable :: params(:), AF(:), MF(:), resid(:)
        real(real64) :: sigma2 = 0.0_real64, aicc = 0.0_real64
        logical :: ok = .false.
    end type sarima_fit_t

    real(real64), allocatable :: g_w(:)
    integer :: g_nw, g_p, g_q, g_sp, g_sq, g_s

contains

    ! polynomial / differencing

    subroutine poly_mul(a, na, b, nb, c, nc)
        real(real64), intent(in) :: a(:), b(:)
        integer, intent(in) :: na, nb
        real(real64), allocatable, intent(out) :: c(:)
        integer, intent(out) :: nc
        integer :: i, j
        nc = na + nb - 1
        allocate(c(nc)); c = 0.0_real64
        do i = 1, na
            do j = 1, nb
                c(i + j - 1) = c(i + j - 1) + a(i) * b(j)
            end do
        end do
    end subroutine poly_mul

    ! AF = (1 - phi.B - …)(1 - Phi.B^s - …)
    subroutine build_ar(phi, p, sphi, sp, s, AF, naf)
        real(real64), intent(in) :: phi(:), sphi(:)
        integer, intent(in) :: p, sp, s
        real(real64), allocatable, intent(out) :: AF(:)
        integer, intent(out) :: naf
        real(real64), allocatable :: a(:), asn(:)
        integer :: k, na, nas
        na = p + 1; allocate(a(na)); a(1) = 1.0_real64
        do k = 1, p; a(k + 1) = -phi(k);
        end do
        nas = s * sp + 1; allocate(asn(nas)); asn = 0.0_real64; asn(1) = 1.0_real64
        do k = 1, sp; asn(k * s + 1) = -sphi(k);
        end do
        call poly_mul(a, na, asn, nas, AF, naf)
    end subroutine build_ar

    ! MF = (1 + theta.B + …)(1 + Theta.B^s + …)
    subroutine build_ma(theta, q, stheta, sq, s, MF, nmf)
        real(real64), intent(in) :: theta(:), stheta(:)
        integer, intent(in) :: q, sq, s
        real(real64), allocatable, intent(out) :: MF(:)
        integer, intent(out) :: nmf
        real(real64), allocatable :: m(:), msn(:)
        integer :: k, nm, nms
        nm = q + 1; allocate(m(nm)); m(1) = 1.0_real64
        do k = 1, q; m(k + 1) = theta(k);
        end do
        nms = s * sq + 1; allocate(msn(nms)); msn = 0.0_real64; msn(1) = 1.0_real64
        do k = 1, sq; msn(k * s + 1) = stheta(k);
        end do
        call poly_mul(m, nm, msn, nms, MF, nmf)
    end subroutine build_ma

    subroutine diff_series(y, ny, d, sd, s, w, nw)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, d, sd, s
        real(real64), allocatable, intent(out) :: w(:)
        integer, intent(out) :: nw
        real(real64), allocatable :: u(:), t(:)
        integer :: k, i, nu
        allocate(u(ny)); u = y(1:ny); nu = ny
        do k = 1, d
            allocate(t(nu - 1))
            do i = 1, nu - 1; t(i) = u(i + 1) - u(i);
            end do
            call move_alloc(t, u); nu = nu - 1
        end do
        do k = 1, sd
            allocate(t(nu - s))
            do i = 1, nu - s; t(i) = u(i + s) - u(i);
            end do
            call move_alloc(t, u); nu = nu - s
        end do
        nw = nu; allocate(w(nw)); w = u(1:nw)
    end subroutine diff_series

    ! e_t: AF(B) w_t = MF(B) e_t
    subroutine css_resid(w, nw, AF, naf, MF, nmf, e)
        real(real64), intent(in) :: w(:), AF(:), MF(:)
        integer, intent(in) :: nw, naf, nmf
        real(real64), intent(out) :: e(:)
        real(real64) :: acc
        integer :: t, i, j
        do t = 1, nw
            acc = 0.0_real64
            do i = 0, naf - 1
                if (t - i >= 1) acc = acc + AF(i + 1) * w(t - i)
            end do
            do j = 1, nmf - 1
                if (t - j >= 1) acc = acc - MF(j + 1) * e(t - j)
            end do
            e(t) = acc
        end do
    end subroutine css_resid

    function objective(x, k) result(sse)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: k
        real(real64) :: sse
        real(real64), allocatable :: AF(:), MF(:), e(:)
        real(real64) :: phi(g_p), theta(g_q), sphi(g_sp), stheta(g_sq)
        integer :: naf, nmf, warmup, t
        if (g_p > 0) phi = x(1:g_p)
        if (g_q > 0) theta = x(g_p + 1:g_p + g_q)
        if (g_sp > 0) sphi = x(g_p + g_q + 1:g_p + g_q + g_sp)
        if (g_sq > 0) stheta = x(g_p + g_q + g_sp + 1:k)
        call build_ar(phi, g_p, sphi, g_sp, g_s, AF, naf)
        call build_ma(theta, g_q, stheta, g_sq, g_s, MF, nmf)
        allocate(e(g_nw)); call css_resid(g_w, g_nw, AF, naf, MF, nmf, e)
        warmup = naf - 1
        if (warmup >= g_nw) then; sse = 1.0e18_real64; return;
        end if
        sse = 0.0_real64
        do t = warmup + 1, g_nw
            sse = sse + e(t) * e(t)
        end do
        if (.not. ieee_is_finite(sse)) sse = 1.0e18_real64
    end function objective

    ! Gaussian elimination with partial pivoting
    subroutine solve_linear(A, b, n, x, ok)
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
    end subroutine solve_linear

    ! Stationarity of the multiplicative AR: roots factor, so the non-seasonal

    function is_stationary(phi, p, sphi, sp) result(ok)
        real(real64), intent(in) :: phi(:), sphi(:)
        integer, intent(in) :: p, sp
        logical :: ok
        real(real64), parameter :: lim = 0.999_real64
        ok = .true.
        if (p == 1) then
            if (abs(phi(1)) >= lim) ok = .false.
        else if (p == 2) then
            if (.not. (abs(phi(2)) < lim .and. phi(1) + phi(2) < lim &
                    .and. phi(2) - phi(1) < lim)) ok = .false.
        else if (p >= 3) then
            ok = .false.
        end if
        if (sp >= 1) then
            if (abs(sphi(1)) >= lim) ok = .false.
        end if
    end function is_stationary

    subroutine ar_ols_init(w, nw, p, phi)
        real(real64), intent(in) :: w(:)
        integer, intent(in) :: nw, p
        real(real64), intent(out) :: phi(:)
        real(real64), allocatable :: XtX(:, :), Xty(:), sol(:)
        integer :: rows, r, i, j
        logical :: ok
        do i = 1, p; phi(i) = 0.0_real64;
        end do
        if (p == 0 .or. nw <= p + 1) return
        rows = nw - p
        allocate(XtX(p, p), Xty(p), sol(p)); XtX = 0.0_real64; Xty = 0.0_real64
        do r = 1, rows
            do i = 1, p
                do j = 1, p
                    XtX(i, j) = XtX(i, j) + w(p - i + r) * w(p - j + r)
                end do
                Xty(i) = Xty(i) + w(p - i + r) * w(p + r)
            end do
        end do
        call solve_linear(XtX, Xty, p, sol, ok)
        if (.not. ok) return
        do i = 1, p
            phi(i) = max(-0.95_real64, min(0.95_real64, sol(i)))
        end do
    end subroutine ar_ols_init

    subroutine nelder_mead(x0, k, xbest)
        real(real64), intent(in) :: x0(:)
        integer, intent(in) :: k
        real(real64), intent(out) :: xbest(:)
        real(real64) :: simplex(k, k + 1), fv(k + 1)
        real(real64) :: cent(k), xr(k), xe(k), xc(k), step
        real(real64) :: fr, fe, fc, tmpf
        integer :: i, j, it, lo, hi, hi2, iters
        real(real64), parameter :: aa = 1.0_real64, gg = 2.0_real64, rr = 0.5_real64, ss = 0.5_real64
        iters = 140
        do i = 1, k; simplex(i, 1) = x0(i);
        end do
        do j = 2, k + 1
            do i = 1, k; simplex(i, j) = x0(i);
            end do
            step = 0.15_real64
            if (x0(j - 1) /= 0.0_real64) step = 0.15_real64 * (1.0_real64 + abs(x0(j - 1)))
            simplex(j - 1, j) = simplex(j - 1, j) + step
        end do
        do j = 1, k + 1; fv(j) = objective(simplex(:, j), k);
        end do
        do it = 1, iter
            lo = 1; hi = 1
            do j = 2, k + 1
                if (fv(j) < fv(lo)) lo = j
                if (fv(j) > fv(hi)) hi = j
            end do
            hi2 = lo
            do j = 1, k + 1
                if (j /= hi .and. fv(j) > fv(hi2)) hi2 = j
            end do
            cent = 0.0_real64
            do j = 1, k + 1
                if (j /= hi) cent = cent + simplex(:, j)
            end do
            cent = cent / real(k, real64)
            xr = cent + aa * (cent - simplex(:, hi)); fr = objective(xr, k)
            if (fr < fv(lo)) then
                xe = cent + gg * (xr - cent); fe = objective(xe, k)
                if (fe < fr) then; simplex(:, hi) = xe; fv(hi) = fe
                else; simplex(:, hi) = xr; fv(hi) = fr;
                end if
            else if (fr < fv(hi2)) then
                simplex(:, hi) = xr; fv(hi) = fr
            else
                xc = cent + rr * (simplex(:, hi) - cent); fc = objective(xc, k)
                if (fc < fv(hi)) then
                    simplex(:, hi) = xc; fv(hi) = fc
                else
                    do j = 1, k + 1
                        if (j /= lo) then
                            simplex(:, j) = simplex(:, lo) + ss * (simplex(:, j) - simplex(:, lo))
                            fv(j) = objective(simplex(:, j), k)
                        end if
                    end do
                end if
            end if
        end do
        lo = 1
        do j = 2, k + 1
            if (fv(j) < fv(lo)) lo = j
        end do
        do i = 1, k; xbest(i) = simplex(i, lo);
        end do
    end subroutine nelder_mead

    subroutine sarima_fit(y, ny, p, d, q, sp, sd, sq, s, fit)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, p, d, q, sp, sd, sq, s
        type(sarima_fit_t), intent(out) :: fit
        real(real64), allocatable :: w(:), x0(:), xb(:), AF(:), MF(:), e(:)
        real(real64) :: phi(max(1, p)), theta(max(1, q)), sphi(max(1, sp)), stheta(max(1, sq))
        real(real64) :: sigma2, aic, aicc
        integer :: nw, nparam, naf, nmf, warmup, nobs, kk, minlen, t
        fit%ok = .false.
        nparam = p + q + sp + sq
        minlen = max(2 * s, p + s * sp + q + s * sq) + 5
        call diff_series(y, ny, d, sd, s, w, nw)
        if (nw < minlen) return
        allocate(x0(max(1, nparam)), xb(max(1, nparam)))
        x0 = 0.0_real64
        if (p > 0) then
            call ar_ols_init(w, nw, p, phi)
            x0(1:p) = phi(1:p)
        end if
        if (allocated(g_w)) deallocate(g_w)
        allocate(g_w(nw)); g_w = w
        g_nw = nw; g_p = p; g_q = q; g_sp = sp; g_sq = sq; g_s = s
        if (nparam > 0) then
            call nelder_mead(x0(1:nparam), nparam, xb(1:nparam))
        end if
        if (p > 0) phi = xb(1:p)
        if (q > 0) theta = xb(p + 1:p + q)
        if (sp > 0) sphi = xb(p + q + 1:p + q + sp)
        if (sq > 0) stheta = xb(p + q + sp + 1:nparam)
        if (.not. is_stationary(phi, p, sphi, sp)) return
        call build_ar(phi, p, sphi, sp, s, AF, naf)
        call build_ma(theta, q, stheta, sq, s, MF, nmf)
        allocate(e(nw)); call css_resid(w, nw, AF, naf, MF, nmf, e)
        warmup = naf - 1
        nobs = nw - warmup
        kk = nparam + 1
        if (nobs <= nparam + 1) return
        sigma2 = 0.0_real64
        do t = warmup + 1, nw; sigma2 = sigma2 + e(t) * e(t);
        end do
        sigma2 = sigma2 / real(nobs, real64)
        if (sigma2 <= 0.0_real64 .or. .not. ieee_is_finite(sigma2)) return
        aic = real(nobs, real64) * log(sigma2) + 2.0_real64 * kk
        aicc = aic + (2.0_real64 * kk * (kk + 1)) / real(max(1, nobs - kk - 1), real64)
        fit%p = p; fit%d = d; fit%q = q; fit%sp = sp; fit%sd = sd; fit%sq = sq; fit%s = s
        fit%naf = naf; fit%nmf = nmf; fit%nw = nw; fit%nparam = nparam
        fit%params = xb(1:max(1, nparam)); fit%AF = AF; fit%MF = MF; fit%resid = e
        fit%sigma2 = sigma2; fit%aicc = aicc; fit%ok = .true.
    end subroutine sarima_fit

    subroutine integrate_forecast(y, ny, wf, h, d, sd, s, yf)
        real(real64), intent(in) :: y(:), wf(:)
        integer, intent(in) :: ny, h, d, sd, s
        real(real64), intent(out) :: yf(:)
        real(real64), allocatable :: u(:), uext(:), yext(:), uf(:)
        integer :: nu, i, k
        ! u = d-th difference of y
        allocate(u(ny)); u = y(1:ny); nu = ny
        do i = 1, d
            u(1:nu - 1) = u(2:nu) - u(1:nu - 1); nu = nu - 1
        end do
        allocate(uf(h))
        if (sd == 1) then
            allocate(uext(nu + h)); uext(1:nu) = u(1:nu)
            do k = 1, h
                uext(nu + k) = wf(k) + uext(nu + k - s)
                uf(k) = uext(nu + k)
            end do
        else
            uf = wf(1:h)
        end if
        if (d == 1) then
            allocate(yext(ny + h)); yext(1:ny) = y(1:ny)
            do k = 1, h
                yext(ny + k) = yext(ny + k - 1) + uf(k)
                yf(k) = yext(ny + k)
            end do
        else
            yf(1:h) = uf(1:h)
        end if
    end subroutine integrate_forecast

    subroutine sarima_forecast(y, ny, fit, h, yf)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, h
        type(sarima_fit_t), intent(in) :: fit
        real(real64), intent(out) :: yf(:)
        real(real64), allocatable :: w(:), wext(:), wf(:)
        real(real64) :: acc, ej
        integer :: nw, pAR, pMA, k, t, i, j
        call diff_series(y, ny, fit%d, fit%sd, fit%s, w, nw)
        pAR = fit%naf - 1; pMA = fit%nmf - 1
        allocate(wext(nw + h)); wext(1:nw) = w(1:nw); allocate(wf(h))
        do k = 1, h
            t = nw + k
            acc = 0.0_real64
            do i = 1, pAR
                acc = acc - fit%AF(i + 1) * wext(t - i)
            end do
            do j = 1, pMA
                if (t - j >= 1 .and. t - j <= nw) then; ej = fit%resid(t - j);
                else; ej = 0.0_real64;
                end if
                acc = acc + fit%MF(j + 1) * ej
            end do
            wf(k) = acc; wext(t) = acc
        end do
        call integrate_forecast(y, ny, wf, h, fit%d, fit%sd, fit%s, yf)
    end subroutine sarima_forecast

    function mase(train, ntr, fc, act, h, m) result(r)
        real(real64), intent(in) :: train(:), fc(:), act(:)
        integer, intent(in) :: ntr, h, m
        real(real64) :: r, scale, mae
        integer :: i
        scale = 0.0_real64
        if (ntr > m) then
            do i = 1, ntr - m; scale = scale + abs(train(i + m) - train(i));
            end do
            scale = scale / real(ntr - m, real64)
        end if
        if (scale <= 0.0_real64 .or. .not. ieee_is_finite(scale)) then
            r = 1.0e18_real64; return
        end if
        mae = 0.0_real64
        do i = 1, h; mae = mae + abs(fc(i) - act(i));
        end do
        r = (mae / real(h, real64)) / scale
    end function mase

    function holdout_mase(y, ny, p, d, q, sp, sd, sq, s, h) result(r)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, p, d, q, sp, sd, sq, s, h
        real(real64) :: r
        type(sarima_fit_t) :: fit
        real(real64), allocatable :: fc(:)
        integer :: ntr, i
        ntr = ny - h
        call sarima_fit(y(1:ntr), ntr, p, d, q, sp, sd, sq, s, fit)
        if (.not. fit%ok) then; r = 1.0e18_real64; return;
        end if
        allocate(fc(h)); call sarima_forecast(y(1:ntr), ntr, fit, h, fc)
        do i = 1, h
            if (.not. ieee_is_finite(fc(i))) then; r = 1.0e18_real64; return;
            end if
        end do
        r = mase(y(1:ntr), ntr, fc, y(ntr + 1:ny), h, s)
    end function holdout_mase

    subroutine auto_select(y, ny, s, h, best)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, s, h
        type(sarima_fit_t), intent(out) :: best
        integer, parameter :: NORD = 9
        integer :: ords(6, NORD), oi, hh
        real(real64) :: key, bestkey
        logical :: can_hold
        type(sarima_fit_t) :: fit
        ! (p,d,q,P,D,Q) grid — mirrors services/sarima.py
        ords(:, 1) = (/ 1, 1, 0, 0, 0, 0 /)
        ords(:, 2) = (/ 0, 1, 1, 0, 0, 0 /)
        ords(:, 3) = (/ 1, 1, 1, 0, 0, 0 /)
        ords(:, 4) = (/ 2, 1, 0, 0, 0, 0 /)
        ords(:, 5) = (/ 0, 1, 1, 1, 0, 0 /)
        ords(:, 6) = (/ 1, 1, 0, 1, 0, 0 /)
        ords(:, 7) = (/ 1, 1, 1, 1, 0, 0 /)
        ords(:, 8) = (/ 0, 1, 1, 0, 0, 1 /)
        ords(:, 9) = (/ 0, 1, 1, 1, 0, 1 /)
        hh = h; if (hh < 1) hh = 1
        can_hold = ny > hh + max(2 * s, 10) + 5
        bestkey = 1.0e18_real64; best%ok = .false.
        do oi = 1, NORD
            call sarima_fit(y, ny, ords(1, oi), ords(2, oi), ords(3, oi), &
                    ords(4, oi), ords(5, oi), ords(6, oi), s, fit)
            if (.not. fit%ok) cycle
            if (can_hold) then
                key = holdout_mase(y, ny, ords(1, oi), ords(2, oi), ords(3, oi), &
                        ords(4, oi), ords(5, oi), ords(6, oi), s, hh)
            else
                key = fit%aicc
            end if
            if (ieee_is_finite(key) .and. key < bestkey) then
                bestkey = key; best = fit
            end if
        end do
    end subroutine auto_select

    subroutine f_sarima(y, ny, h, s, yf, ok)
        real(real64), intent(in) :: y(:)
        integer, intent(in) :: ny, h, s
        real(real64), intent(out) :: yf(:)
        logical, intent(out) :: ok
        type(sarima_fit_t) :: fit
        integer :: i
        call auto_select(y, ny, s, h, fit)
        ok = fit%ok
        if (.not. ok) return
        call sarima_forecast(y, ny, fit, h, yf)
        do i = 1, h
            if (.not. ieee_is_finite(yf(i))) then; ok = .false.; return;
            end if
        end do
    end subroutine f_sarima

end module forecast_mod
