# Calcule GNU Octave pentru PSIM

Fluxul normal se porneste prin `start.bat` din radacina. Orchestratorul
lanseaza numai `run_psim_supervisor()`.

- `run_psim_supervisor.m`: bucla de receptie, comenzi, persistenta si oprire.
  Nu genereaza o evolutie simulata de turatie sau semnale electrice.
- `create_psim_receiver.m` / `process_psim_sample.m`: receptie TCP cu linii
  fragmentate, validare, contoare, ultimul cadru si reset de sesiune.
- `publish_psim_status.m`: metadate, liveness si ultimul cadru brut,
  actualizate la aproximativ 200 ms reale.
- `diagnostic_psim.m`: RMS estimat, preincarcare, turatie sincrona si
  conditii informative calculate din semnalele PSIM.
- `control_psim.m`: comenzi si heartbeat catre DLL, identitatea canalului si ACK.
- Functiile CSV/JSON: persistenta segmentata si metadate cu identitatea executiei.
- `src` si `scripts/run_baseline.m`: modelul analitic initial pentru calcule
  separate. Rezultatele vechi au fost eliminate din `results` la cererea
  utilizatorului; o rulare explicita a calculelor poate genera rezultate noi.
- `tests/test_psim_diagnostics.m`: verifica preincarcarea, RMS si ciclul
  de alarma/revenire pe esantioane de test izolate.

Configuratia este `../config/app_config.json`; orchestratorul transmite o
copie validata prin `IDRIVE_CONFIG_RUNTIME`. Receptia necesita pachetul
`instrument-control`. Nu porni alt receptor pe portul 5050.
Pragurile sunt informative. RMS estimat din telemetria la 1 ms nu este o
validare true-RMS a curentului PWM.

