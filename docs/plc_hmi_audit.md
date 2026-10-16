# Auditul controlului PLC-HMI - 12 octombrie 2026

## Diferente constatate si corectate

| Impact | Constatare initiala | Corectie |
| --- | --- | --- |
| Critic | Browserul trimitea START automat la prima conexiune DLL. | Pornirea automata a fost eliminata din UI si API. START cere actiunea operatorului. |
| Ridicat | DLL accepta START inainte de calificarea DC-link si astepta ulterior preincarcarea. | Controlerul refuza START cu motiv explicit pana cand tensiunea este stabila. |
| Ridicat | `RUNNING` era decis numai din referinta de frecventa. | Starea cere si turatie masurata in interval, stabila 0,2 s simulate. |
| Ridicat | Oprirea cu PWM dezactivat si rotor in miscare era prezentata tot ca STOPPING. | Starea COASTING separa rotirea prin inertie; STOPPED cere turatie sub 10 RPM timp de 0,1 s. |
| Mediu | Cererile respinse in DLL ramaneau fara motiv si expirau in HMI. | NACK identifica secventa si motivul; Octave nu o retransmite. |
| Mediu | Octave putea mentine heartbeat-ul dupa disparitia backendului. | Lease-ul backendului opreste retransmiterea; watchdog-ul DLL blocheaza PWM. |
| Mediu | STOP repetat crea secvente suplimentare. | API raspunde idempotent, pastrand prioritatea STOP fata de START in asteptare. |
| Mediu | HMI si diagnosticul Octave puteau afisa doua stari diferite drept stare a actionarii. | Starea actionarii afisata vine din DLL; diagnosticul Octave ramane informativ. |
| Mediu | Detectia blocarii rotorului nu tinea cont de curent. | Dupa stabilizarea F_REF, curentul ridicat si turatia mica indica blocare; cu curent mic, timeout-ul indica accelerare nereusita. |

## Autoritate si flux

HMI trimite numai cereri. Python verifica schema, intervalele, prospetimea
datelor si identitatea canalului. Octave valideaza din nou inainte de transport.
DLL-ul decide definitiv permisivele, secventa, PWM, rampa si defectele la
fiecare pas numeric PSIM. PSIM calculeaza raspunsul electric si mecanic.
Octave calculeaza RMS si avertizari din telemetrie pentru HMI/CSV, fara
drept de comanda directa asupra PWM. MQTT transmite doar telemetrie.

Nu exista un ciclu PLC hardware. Callback-ul DLL citeste intrarile PSIM,
evalueaza defectele si starea, apoi scrie iesirile. Transportul TCP este
neblocant si decimat la aproximativ 1 ms simulat; Octave proceseaza si
publica aproximativ la 0,2 s reale, iar HMI interogheaza la 0,75 s reale.
Timpul simulat guverneaza rampele si pragurile dinamice. Ceasul real
guverneaza disponibilitatea comunicatiei si watchdog-ul. Windows nu ofera
garantii hard real-time pentru acest lant.

## Stari si comenzi

| Stare DLL | Intrare si iesire | Comenzi si iesiri |
| --- | --- | --- |
| PRECHARGE | DC-link inca necalificat; dupa 0,1 s in 510..610 V trece la READY. | START refuzat, PWM 0; STOP permis. |
| READY | DC-link calificat, rotor oprit, fara rulare anterioara; START trece la STARTING. | START permis, PWM 0 pana la acceptare. |
| STARTING | START acceptat si PWM activ; rampa urca spre tinta. Feedback stabil 0,2 s trece la RUNNING. | Referinte noi prin rampa; STOP trece la STOPPING. |
| RUNNING | Frecventa interna si F_REF aproape de tinta, turatie masurata compatibila. | Referinte noi pot readuce STARTING; STOP trece la STOPPING. |
| STOPPING | STOP acceptat, PWM mentinut cat timp frecventa scade. | START refuzat. La F_REF cel mult 0,2 Hz, PWM 0; urmeaza COASTING daca rotorul se misca. |
| COASTING | PWM 0 si rotorul inca se roteste, sau asteptarea stabilitatii sub 10 RPM. | START refuzat. Sub 10 RPM timp de 0,1 s trece la STOPPED. |
| STOPPED | Rotor stabil sub prag dupa o rulare; DC-link calificat. | START nou permis; PWM 0. |
| FAULT | Defect memorat, inclusiv pierdere de comunicatie; PWM 0 imediat. | START refuzat. RESET permis numai dupa revenirea conditiilor; nu porneste motorul. |

STOP normal poate duce la rotire libera dupa oprirea PWM. Defectul opreste
PWM imediat; turatia poate ramane nenula din inertie, iar HMI afiseaza
defectul memorat si turatia masurata. Nu exista frenare activa garantata.
Sarcina mecanica ramane aplicata cand PWM este oprit, conform blocului
LOAD_MECH cu Speed Flag 0, si scade gradual sub 50 RPM. Ea franeaza rotorul
in rotirea prin inertie, fara modelarea unei sarcini gravitationale.

## Confirmari si jurnal

HTTP 202 inseamna cerere scrisa pentru Octave, nu executie. ACK-ul DLL cu
aceeasi secventa inseamna acceptare. NACK inseamna refuz explicit.
`pwm_enabled` si `drive_state` arata efectul asupra controlului; F_REF si
RPM arata raspunsul masurat. Daca nu apare raspunsul, HMI arata cererea
neconfirmata. Octave scrie evenimentele `CMD_ACCEPTED`, `CMD_REJECT_*`
si `DRIVE_*` in CSV cand exista sesiune activa. Repetarea secventei acceptate
mentine doar heartbeat-ul si nu reaplica rampa sau RESET.

## Pierderi de comunicatie

| Legatura | Comportament |
| --- | --- |
| Tab HMI - backend | Tabul pierde operarea; backendul si controlerul continua. Revenirea sincronizeaza starea, fara START automat. |
| Backend - Octave | Lease-ul expira dupa 2 s reale; Octave nu mai trimite heartbeat. DLL declanseaza defectul de comunicatie. |
| Octave - DLL/PSIM | Socketul inchis sau watchdog de 2 s cu motor comandat blocheaza imediat PWM si memoreaza defectul. |
| DLL - PSIM | DLL-ul se executa in callback PSIM; la oprirea simularii nu mai exista masuratori proaspete si HMI retrage controlul. |
| Backend - MQTT | Telemetria MQTT devine indisponibila; motorul nu este oprit. |

Terminarea normala PSIM si caderea procesului PSIM nu au inca un semnal
distinct garantat prin protocol. Ambele retrag controlul prin expirarea
datelor; un circuit care se opreste neasteptat necesita inspectia PSIM.

## Limite tehnice ramase

- Parametrii nominali 4 kW, 400 V, 8,2 A, 1430 RPM si purtatoarea 2 kHz sunt
  provizorii. Nu au fost confirmati din configuratia completa PSIM.
- FREQ_RAMP exterior poate incetini rampa DLL; pantele sale reale trebuie
  verificate in PSIM. Nici forma purtatoarei, nici tensiunea fundamentala
  rezultata din VF_GAIN=0,016 nu au fost validate pe circuit.
- Se masoara curentul unei singure faze. RMS-ul Octave la 1 ms este
  informativ; RMS-ul de protectie in DLL foloseste esantioanele solverului.
- Pragurile de supracurent, supraturatie, blocare si modelul termic sunt
  protectii simulate. Nu inlocuiesc relee, STO, E-stop sau protectii certificate.
- Cota CSV de 512 MiB nu limiteaza memoria sau fisierele native PSIM.
- DLL-ul compilat a fost verificat cu o gazda x86 izolata; schema PSIM reala
  trebuie sa incarce `psim_drive_control_plc.dll` si sa fie observata la
  START, STOP, inertie si fault inainte de a declara validata fizica motorului.
