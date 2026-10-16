function settings = load_motor_config()
  file_path = getenv('IDRIVE_CONFIG_RUNTIME');
  if isempty(file_path)
    root_dir = fileparts(fileparts(mfilename('fullpath')));
    file_path = fullfile(root_dir, 'config', 'app_config.json');
  endif
  settings = jsondecode(fileread(file_path));
  if isempty(getenv('IDRIVE_CONFIG_RUNTIME'))
    settings.director_rezultate = fullfile(root_dir, settings.director_rezultate);
    settings.orchestrator_id = 'octave_manual';
    settings.fisier_oprire = fullfile(settings.director_rezultate, 'oprire_manual.flag');
    settings.director_control = fullfile(settings.director_rezultate,'runtime','octave_manual');
  endif
  if !isfield(settings,'control')
    settings.control = struct('frecventa_max_hz',50,'sarcina_max_nm',10,'expirare_comanda_s',5,'psim_activ',false);
  endif
  if exist(settings.director_control,'dir') != 7, mkdir(settings.director_control); endif
endfunction
