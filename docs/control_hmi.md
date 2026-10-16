# Controlul motorului din HMI

PSIM calculeaza circuitul si motorul. DLL-ul x86 este singura autoritate pentru
secventa actionarii, PWM, rampe si defecte. Octave transporta comenzi validate,
prelucreaza masuratori, calculeaza diagnosticul informativ si scrie CSV. Python
serveste HMI-ul si verifica disponibilitatea canalului. MQTT publica telemetrie,
fara cale de comanda catre motor.

## Pornire si operare

1. Inchide simularea si PSIM inainte de schimbarea DLL-ului incarcat. In General
   DLL Block `PSIM_OCTAVE_HMI`, selecteaza calea absoluta catre
   `bridge/psim_drive_control_plc.dll`. Pastreaza cele 4 intrari si 3 iesiri.
2. Porneste `start.bat`, apoi deschide schema in PSIM si porneste simularea cu F8.
   Aplicatia nu trimite START la pornire, refresh sau reconectare.
3. Asteapta starea `Pregatit`. Introdu frecventa, sarcina si timpii de rampa,
   apoi apasa START. Implicit: 50 Hz, 5 Nm, accelerare 2 s, decelerare 5 s.
4. Comanda este mai intai solicitata, apoi acceptata sau respinsa de DLL.
   `Accelerare` indica PWM activ si rampa in curs. `In functionare` necesita
   si o turatie masurata apropiata de viteza sincrona, stabila 0,2 s simulate.
5. STOP scade referinta de frecventa cu PWM activ. Dupa ce referinta interna
   este aproape zero si F_REF masurat este cel mult 0,2 Hz, PWM se opreste.
   Cat timp rotorul mai are cel putin 10 RPM, starea este `Rotire prin inertie`.
   `Oprit` necesita sub 10 RPM timp de 0,1 s simulate.
6. Un defect blocheaza imediat PWM si ramane memorat. RESET este acceptat numai
   dupa disparitia cauzei, cu rotor oprit, DC-link pregatit si curent revenit.
   RESET nu trimite START.

START este respins la preincarcare neterminata, defect memorat, rotor in miscare
sau oprire in curs. STOP are prioritate fata de START in asteptare. Comenzile
START/STOP repetate nu relanseaza secventele. Frecventa este limitata la 0..50 Hz,
sarcina la 0..10 Nm; accelerarea la 1..30 s si decelerarea la 2..60 s. START
necesita frecventa pozitiva. Valorile invalide sunt respinse, nu saturate.
Referintele se pot schimba in functionare, iar DLL-ul aplica noua tinta prin
rampa. Sensul invers, franarea activa si pornirea din mers nu sunt suportate.

## Conexiunile PSIM

| Port | Semnal | Conexiune |
| --- | --- | --- |
| IN1 | MOTOR_RPM | Senzorul de turatie existent |
| IN2 | I_MOTOR_U | Curentul instantaneu al fazei U |
| IN3 | VDC_LINK | Tensiunea magistralei c.c. |
| IN4 | F_REF | Frecventa dupa blocul FREQ_RAMP |
| OUT1 | F_TARGET | Intrarea FREQ_RAMP |
| OUT2 | RUN | Intrarea AND_HMI_ENABLE impreuna cu PWM_ENABLE |
| OUT3 | LOAD | Intrarea de cuplu a LOAD_MECH, in Nm |

OUT2 semnifica autorizarea PWM, nu butonul START. Ramane activ in timpul
decelerarii normale. Pastreaza FREQ_RAMP ca limitator secundar. Pentru timpii
HMI exacti, pantele sale trebuie sa permita cel putin 50 Hz/s in ambele
directii; verifica unitatile in proprietatile PSIM inainte de modificare.
Sarcina comandata ramane cuplata mecanic si in timpul rotirii prin inertie;
este redusa sub 50 RPM pentru a evita trecerea inversa prin zero. Aceasta
alegere foloseste LOAD_MECH cu Speed Flag 0, care opune cuplul miscarii.
Modelul nu reprezinta un troliu sau o sarcina care antreneaza singura rotorul.

## Protectii si legaturi

Pragurile sunt in `config/app_config.json` si raman provizorii pana la
verificarea motorului PSIM: 8,2 A nominal, 12,3 A RMS timp de 0,2 s,
varf aproximativ 34,8 A, DC-link sub 470 V timp de 0,05 s cu PWM activ,
peste 650 V imediat, turatie peste 1650 RPM, rotor blocat 3 s dupa
stabilizarea F_REF cand curentul RMS depaseste jumatate din nominal,
accelerare nereusita dupa 5 s cu viteza mica si curent mai redus,
suprasarcina termica simplificata si timeout de oprire.
RMS-ul de protectie este calculat in DLL din fiecare pas numeric PSIM pe o
fereastra de 20 ms. RMS-ul afisat de Octave provine din esantioane TCP de
1 ms si poate fi afectat de aliasing PWM; este diagnostic informativ.
Se masoara doar faza U.

Toate conditiile din tabel au severitatea DEFECT: PWM se blocheaza imediat,
defectul ramane memorat si necesita RESET dupa revenirea conditiei. Evenimentul
`DRIVE_FAULT` contine codul numeric al defectului cand legatura de date permite
scrierea in jurnal. Pentru pierderea legaturii, jurnalizarea poate aparea abia
dupa reconectare; istoricul local nu poate dovedi fiecare defect produs offline.

| Defect | Semnal si conditie de activare | Revenire necesara pentru RESET |
| --- | --- | --- |
| Supracurent | Faza U: varf peste ~34,8 A imediat sau RMS 20 ms peste 12,3 A timp de 0,2 s | RMS sub 11,07 A, rotor oprit, DC-link pregatit |
| Subtensiune | VDC_LINK sub 470 V timp de 0,05 s cu PWM activ | DC-link stabil 510..610 V timp de 0,1 s |
| Supratensiune | VDC_LINK peste 650 V, imediat | DC-link stabil 510..610 V timp de 0,1 s |
| Supraturatie | Valoarea absoluta MOTOR_RPM peste 1650, imediat | Sub 10 RPM stabil 0,1 s |
| Comunicare | Heartbeat CMD lipsa peste 2 s reale cu motor comandat sau socket inchis | Legatura restabilita, rotor oprit si RESET manual |
| Masuratori invalide | Intrare PSIM nefinita, DC negativ, F_REF negativ sau pas numeric invalid | Masuratori valide si rotor oprit stabil |
| Oprire nefinalizata | PWM sau rotire prin inertie persista peste durata decelerarii +20 s simulate | Rotor oprit stabil si DC-link pregatit |
| Preincarcare nefinalizata | Dupa START acceptat, DC-link pierde calificarea si nu revine in 10 s simulate | DC-link stabil 510..610 V |
| Suprasarcina termica | Integrala simplificata I2t depaseste 20 s | Integrala scade sub 5 s si curentul revine |
| Rotor blocat | F_REF stabil peste 5 Hz, turatie sub 20% din viteza sincrona si RMS peste 50% nominal timp de 3 s | Rotor oprit stabil, curent revenit |
| Accelerare nereusita | Aceeasi abatere de turatie persista 5 s cu RMS mai mic | Rotor oprit stabil si cauza investigata |

RESET mai cere in toate cazurile PWM oprit si tensiunea DC-link in intervalul
calificat. Avertizarile Octave folosesc praguri si histerezis separate; ele
sunt informative, nu declanseaza singure iesirea PWM.

DLL-ul primeste heartbeat prin Octave. Absenta comenzii timp de `watchdog_s`
(implicit 2 s reale) sau inchiderea TCP cu motorul comandat produce defect
de comunicatie si PWM oprit. Octave verifica periodic fisierul de lease al
backendului; daca backendul dispare, nu mai mentine heartbeat-ul DLL.
Inchiderea numai a tabului HMI nu opreste motorul cat timp backendul si
Octave sunt active. MQTT nu participa la interblocari si pierderea sa nu
opreste motorul. Dupa reconectare nu se reaplica o comanda veche, iar un
defect memorat cere RESET si apoi START nou.

## Protocol si confirmare

```text
DLL -> Octave: HELLO,HMI,2
Octave -> DLL: CFG,maxHz,maxLoad,ratedA,tripA,lowV,highV,maxRPM,readyLowV,readyHighV,watchdogS
Octave -> DLL: CMD,sequence,requestedRun,frequencyHz,loadNm,accelerationS,decelerationS,reset
DLL -> Octave: ACK,sequence,requestedRun,frequencyHz,loadNm,watchdog,2,state,fault,pwmEnabled,outputHz,accelerationS,decelerationS,configured
DLL -> Octave: NACK,sequence,reason
```

Cererea HTTP primeste un identificator secvential si identitatea conexiunii.
ACK inseamna ca DLL-ul a acceptat cererea. PWM si starea confirma aplicarea
la iesiri. F_REF si MOTOR_RPM masurate confirma efectul in circuit. NACK
furnizeaza motivul refuzului. Comenzile expirate si cele de pe o conexiune
veche nu sunt retransmise. Evenimentele de acceptare, refuz si tranzitie
sunt scrise in jurnalul CSV atunci cand sesiunea de masurare este activa.

## Simulare si limite

Pentru purtatoarea declarata de 2 kHz, pasul numeric de 1e-6 s ofera
aproximativ 500 pasi pe perioada PWM. Free Run continua pana la oprirea
manuala. Print step 1000 reduce datele Simview la circa 1000 puncte pe
secunda simulata pentru fiecare semnal, dar nu schimba pasul numeric sau
protectia DLL. Cota CSV de 512 MiB nu limiteaza fisierele native SMV PSIM.
Pragurile motorului de 4 kW, 400 V, 8,2 A si 1430 RPM nu sunt confirmate
din eticheta sau documentatia motorului. Sistemul este o simulare de control;
nu implementeaza protectii hardware certificate, STO, franare de siguranta
sau garantii hard real-time Windows.
