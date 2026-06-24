! Test/inspection shell for the native SARIMA
program forecasttest
    use, intrinsic :: iso_fortran_env, only : input_unit, output_unit, error_unit, real64
    use json_mod
    use forecast_mod, only : sarima_fit_t, sarima_fit, sarima_forecast, auto_select
    implicit none
    character(len = :), allocatable :: buf, chunkbuf
    character(len = 65536) :: chunk
    integer :: ios, nread
    real(real64), allocatable :: y(:), yf(:), phi(:), theta(:), sphi(:), stheta(:)
    integer :: ny, mode, p, d, q, sp, sd, sq, s, h, off
    type(sarima_fit_t) :: fit
    type(jbuilder) :: b

    buf = ''
    do
        read(input_unit, '(A)', advance = 'no', size = nread, iostat = ios) chunk
        if (nread > 0) buf = buf // chunk(1:nread)
        if (is_iostat_eor(ios)) then; buf = buf // ' '; cycle;
        end if
        if (ios /= 0) exit
    end do

    call get_f64_array(buf, 'y', y, ny)
    mode = get_int_or(buf, 'mode', 1)
    p = get_int_or(buf, 'p', 1); d = get_int_or(buf, 'd', 1); q = get_int_or(buf, 'q', 1)
    sp = get_int_or(buf, 'P', 0); sd = get_int_or(buf, 'D', 0); sq = get_int_or(buf, 'Q', 0)
    s = get_int_or(buf, 's', 7); h = get_int_or(buf, 'h', 30)
    if (ny < 1) then
        write(error_unit, '(A)') 'forecast-test: empty series'; stop 1
    end if

    if (mode == 1) then
        call auto_select(y, ny, s, h, fit)
    else
        call sarima_fit(y, ny, p, d, q, sp, sd, sq, s, fit)
    end if

    call jb_init(b)
    call jb_push(b, '{"ok":')
    if (fit%ok) then; call jb_push(b, 'true');
    else; call jb_push(b, 'false');
    end if
    if (.not. fit%ok) then
        call jb_push(b, '}')
        write(output_unit, '(A)', advance = 'no') jb_str(b); stop 0
    end if

    p = fit%p; q = fit%q; sp = fit%sp; sq = fit%sq
    allocate(phi(max(1, p)), theta(max(1, q)), sphi(max(1, sp)), stheta(max(1, sq)))
    if (p > 0) phi = fit%params(1:p)
    if (q > 0) theta = fit%params(p + 1:p + q)
    if (sp > 0) sphi = fit%params(p + q + 1:p + q + sp)
    if (sq > 0) stheta = fit%params(p + q + sp + 1:p + q + sp + sq)

    allocate(yf(h)); call sarima_forecast(y, ny, fit, h, yf)

    call jb_push(b, ',"order":')
    call jb_int_array(b, (/ fit%p, fit%d, fit%q, fit%sp, fit%sd, fit%sq /), 6)
    call jb_push(b, ',"phi":'); call jb_f64_array(b, phi, p)
    call jb_push(b, ',"theta":'); call jb_f64_array(b, theta, q)
    call jb_push(b, ',"Phi":'); call jb_f64_array(b, sphi, sp)
    call jb_push(b, ',"Theta":'); call jb_f64_array(b, stheta, sq)
    call jb_push(b, ',"aicc":'); call jb_f64(b, fit%aicc)
    call jb_push(b, ',"sigma2":'); call jb_f64(b, fit%sigma2)
    call jb_push(b, ',"forecast":'); call jb_f64_array(b, yf, h)
    call jb_push(b, '}')
    write(output_unit, '(A)', advance = 'no') jb_str(b)
end program forecasttest
