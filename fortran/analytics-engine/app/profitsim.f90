program profitsim
    use, intrinsic :: iso_fortran_env, only : input_unit, output_unit, error_unit
    use montecarlo_mod, only : build_sim_report
    implicit none
    character(len = :), allocatable :: buf, out
    character(len = 65536) :: chunk
    integer :: ios, nread

    buf = ''
    do
        read(input_unit, '(A)', advance = 'no', size = nread, iostat = ios) chunk
        if (nread > 0) buf = buf // chunk(1:nread)
        if (is_iostat_eor(ios)) then
            buf = buf // ' '
            cycle
        end if
        if (ios /= 0) exit
    end do

    out = build_sim_report(buf)
    if (len(out) == 0) then
        write(error_unit, '(A)') 'profit-sim: empty or malformed request'
        stop 1
    end if
    write(output_unit, '(A)', advance = 'no') out
end program profitsim
