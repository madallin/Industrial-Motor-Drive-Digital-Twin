function write_json_atomic(file_path, value)
  temporary = [file_path '.tmp'];
  file = fopen(temporary, 'w');
  if file < 0, error('Nu pot scrie %s', temporary); endif
  unwind_protect
    fprintf(file, '%s\n', jsonencode(value));
  unwind_protect_cleanup
    fclose(file);
  end_unwind_protect
  % A Windows reader may briefly block replacement. Retry without exposing
  % a partially written JSON document.
  for attempt = 1:10
    [status, message] = rename(temporary, file_path);
    if status == 0, return; endif
    pause(0.02);
  endfor
  error('Nu pot actualiza %s: %s', file_path, message);
endfunction
