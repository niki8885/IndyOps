! forecast-engine: native panel forecast for one item
program forecastcalc
    use, intrinsic :: iso_fortran_env, only : input_unit, output_unit, error_unit, real64
    use json_mod
    use forecast_panel_mod, only : forecast_one_json
    implicit none
    character(len = :), allocatable :: buf
    character(len = 65536) :: chunk
    integer :: ios, nread, nv, np, h, s
    real(real64), allocatable :: price(:), volume(:)
    type(jbuilder) :: b
    integer, parameter :: volpanel(5) = (/ 1, 3, 5, 4, 6 /)
    integer, parameter :: pricepanel(5) = (/ 1, 2, 3, 5, 6 /)

    buf = ''
    do
        read(input_unit, '(A)', advance = 'no', size = nread, iostat = ios) chunk
        if (nread > 0) buf = buf // chunk(1:nread)
        if (is_iostat_eor(ios)) then; buf = buf // ' '; cycle;
        end if
        if (ios /= 0) exit
    end do

    call get_f64_array(buf, 'price', price, np)
    call get_f64_array(buf, 'volume', volume, nv)
    h = get_int_or(buf, 'horizon', 30)
    s = get_int_or(buf, 'season', 7)
    if (nv < 1 .or. h < 1) then
        write(error_unit, '(A)') 'forecast-engine: empty series'; stop 1
    end if

    call jb_init(b)
    call jb_push(b, '{')
    call forecast_one_json(b, 'volume', volpanel, 5, volume, nv, h, s, .true.)
    call jb_push(b, ',')
    call forecast_one_json(b, 'price', pricepanel, 5, price, np, h, s, .false.)
    call jb_push(b, '}')
    write(output_unit, '(A)', advance = 'no') jb_str(b)
end program forecastcalc
