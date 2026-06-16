! Distribution primitives for the Monte-Carlo profit simulator (profit-sim binary).

module distrib_mod
    use, intrinsic :: iso_fortran_env, only : real64
    implicit none
    private
    public :: norm_cdf, norm_ppf, student_t_cdf, quantile_grid_interp

    real(real64), parameter :: SQRT2 = 1.4142135623730950488016887_real64

contains

    elemental function norm_cdf(z) result(p)
        real(real64), intent(in) :: z
        real(real64) :: p
        p = 0.5_real64 * (1.0_real64 + erf(z / SQRT2))
    end function norm_cdf

    ! Inverse normal CDF Φ⁻¹ (Acklam) — same coefficients as services._special.norm_ppf.
    elemental function norm_ppf(p_in) result(z)
        real(real64), intent(in) :: p_in
        real(real64) :: z, p, q, r
        real(real64), parameter :: a(6) = [ &
                -3.969683028665376e+01_real64, 2.209460984245205e+02_real64, -2.759285104469687e+02_real64, &
                        1.383577518672690e+02_real64, -3.066479806614716e+01_real64, 2.506628277459239e+00_real64]
        real(real64), parameter :: b(5) = [ &
                -5.447609879822406e+01_real64, 1.615858368580409e+02_real64, -1.556989798598866e+02_real64, &
                        6.680131188771972e+01_real64, -1.328068155288572e+01_real64]
        real(real64), parameter :: c(6) = [ &
                -7.784894002430293e-03_real64, -3.223964580411365e-01_real64, -2.400758277161838e+00_real64, &
                        -2.549732539343734e+00_real64, 4.374664141464968e+00_real64, 2.938163982698783e+00_real64]
        real(real64), parameter :: d(4) = [ &
                7.784695709041462e-03_real64, 3.224671290700398e-01_real64, 2.445134137142996e+00_real64, &
                        3.754408661907416e+00_real64]
        real(real64), parameter :: plow = 0.02425_real64, phigh = 0.97575_real64
        p = min(max(p_in, 1.0e-15_real64), 1.0_real64 - 1.0e-15_real64)
        if (p < plow) then
            q = sqrt(-2.0_real64 * log(p))
            z = (((((c(1) * q + c(2)) * q + c(3)) * q + c(4)) * q + c(5)) * q + c(6)) / &
                    ((((d(1) * q + d(2)) * q + d(3)) * q + d(4)) * q + 1.0_real64)
        else if (p > phigh) then
            q = sqrt(-2.0_real64 * log(1.0_real64 - p))
            z = -(((((c(1) * q + c(2)) * q + c(3)) * q + c(4)) * q + c(5)) * q + c(6)) / &
                    ((((d(1) * q + d(2)) * q + d(3)) * q + d(4)) * q + 1.0_real64)
        else
            q = p - 0.5_real64
            r = q * q
            z = (((((a(1) * r + a(2)) * r + a(3)) * r + a(4)) * r + a(5)) * r + a(6)) * q / &
                    (((((b(1) * r + b(2)) * r + b(3)) * r + b(4)) * r + b(5)) * r + 1.0_real64)
        end if
    end function norm_ppf

    ! Continued fraction for the incomplete beta (Lentz) — matches _special._betacf.
    pure function betacf(a, b, x) result(h)
        real(real64), intent(in) :: a, b, x
        real(real64) :: h, cc, dd, aa, del, qab, qap, qam
        real(real64), parameter :: tiny = 1.0e-30_real64, eps = 3.0e-14_real64
        integer :: m, m2
        qab = a + b; qap = a + 1.0_real64; qam = a - 1.0_real64
        cc = 1.0_real64
        dd = 1.0_real64 - qab * x / qap
        if (abs(dd) < tiny) dd = tiny
        dd = 1.0_real64 / dd
        h = dd
        do m = 1, 300
            m2 = 2 * m
            aa = real(m, real64) * (b - m) * x / ((qam + m2) * (a + m2))
            dd = 1.0_real64 + aa * dd; if (abs(dd) < tiny) dd = tiny
            cc = 1.0_real64 + aa / cc; if (abs(cc) < tiny) cc = tiny
            dd = 1.0_real64 / dd; h = h * dd * cc
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            dd = 1.0_real64 + aa * dd; if (abs(dd) < tiny) dd = tiny
            cc = 1.0_real64 + aa / cc; if (abs(cc) < tiny) cc = tiny
            dd = 1.0_real64 / dd; del = dd * cc; h = h * del
            if (abs(del - 1.0_real64) < eps) exit
        end do
    end function betacf

    ! Regularised incomplete beta Iₓ(a,b) — matches _special._betai.
    pure function betai(a, b, x) result(r)
        real(real64), intent(in) :: a, b, x
        real(real64) :: r, bt, xc
        xc = min(max(x, 0.0_real64), 1.0_real64)
        if (xc <= 0.0_real64 .or. xc >= 1.0_real64) then
            bt = 0.0_real64
        else
            bt = exp(log_gamma(a + b) - log_gamma(a) - log_gamma(b) &
                    + a * log(xc) + b * log(1.0_real64 - xc))
        end if
        if (xc < (a + 1.0_real64) / (a + b + 2.0_real64)) then
            r = bt * betacf(a, b, xc) / a
        else
            r = 1.0_real64 - bt * betacf(b, a, 1.0_real64 - xc) / b
        end if
    end function betai

    ! Student-t CDF Tν(t) = 1 − ½·I_{ν/(ν+t²)}(ν/2, ½) for t≥0 — matches _special.student_t_cdf.
    pure function student_t_cdf(t, df) result(p)
        real(real64), intent(in) :: t, df
        real(real64) :: p, x, ib
        x = df / (df + t * t)
        ib = betai(df / 2.0_real64, 0.5_real64, x)
        if (t >= 0.0_real64) then
            p = 1.0_real64 - 0.5_real64 * ib
        else
            p = 0.5_real64 * ib
        end if
    end function student_t_cdf

    pure function quantile_grid_interp(grid, k, u) result(v)
        real(real64), intent(in) :: grid(:)
        integer, intent(in) :: k
        real(real64), intent(in) :: u
        real(real64) :: v, pos, frac
        integer :: lo
        pos = max(0.0_real64, min(1.0_real64, u)) * real(k - 1, real64)
        lo = floor(pos)
        if (lo > k - 2) lo = k - 2
        if (lo < 0) lo = 0
        frac = pos - real(lo, real64)
        v = grid(lo + 1) + frac * (grid(lo + 2) - grid(lo + 1))
    end function quantile_grid_interp

end module distrib_mod
