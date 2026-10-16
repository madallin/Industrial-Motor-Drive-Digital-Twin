# Unde verifici datele PSIM

## 1. In proprietatile General DLL Block

Blocul `PSIM_OCTAVE_HMI` trebuie sa aiba 4 intrari, 3 iesiri si calea completa
catre `bridge/psim_drive_control_plc.dll`. Simularea se porneste manual cu F8, dupa pornirea
aplicatiei. Denumirea blocului singura nu stabileste ce DLL foloseste.

## 2. In Operare si pe grafic

Interfata operatorului arata starea conexiunii, masuratorile si comanda motorului.
Selecteaza un semnal si deplaseaza cursorul pe grafic: punctul, timpul si valoarea
sunt afisate langa esantion. Compara in Simview la **acelasi timp simulat**.
Graficul foloseste puncte agregate; CSV pastreaza esantioanele receptionate.
RMS este calculat in Octave, celelalte patru semnale provin din PSIM.

Dupa sfarsitul rularii, valorile curente — si controlul indisponibil sunt normale.
Graficul este etichetat ca ultima rulare inregistrata; nu reprezinta masuratori
curente. In Inregistrari poti selecta si alte semnale ale acelei rulari.

Pentru verificarea tehnica a transportului foloseste
http://127.0.0.1:8765/api/stare, sectiunea `receptie`, sau
`results/stare_receptie_psim.json`. Aceste detalii nu mai ocupa ecranul HMI.
`cadre_valide` creste in timpul rularii, `cadre_respinse` trebuie sa ramana zero,
iar `ultim_cadru` contine valorile decodate inainte de RMS si diagnostic.

| Camp din ultim_cadru | Intrare DLL | Compara in Simview cu |
| --- | --- | --- |
| t_s | Timp furnizat de PSIM | Axa timp [s] |
| rpm | IN1 | MOTOR_RPM [RPM] |
| phase_current_a | IN2 | I_MOTOR_U [A], instantaneu si cu acelasi semn |
| vdc_v | IN3 | VDC_LINK [V] |
| f_ref_hz | IN4 | F_REF [Hz], dupa FREQ_RAMP |

Formatul TCP ramane `t_s,rpm,phase_current_A,dc_voltage_V,f_ref_Hz` plus LF.
Timpul este transmis cu 6 zecimale, valorile cu 9 cifre semnificative;
afisarile HMI sunt rotunjite. Un timp care nu creste este respins; un reset
cu mai mult de 0,01 s deschide o sesiune noua. Contoarele sunt cumulate pentru
executia aplicatiei. Lipsa traficului retrage starea de conexiune dupa 3 s;
un socket detectat nu dovedeste date proaspete.

## 3. In Inregistrari / CSV

Selecteaza sesiunea PSIM cea mai recenta. Ultimele esantioane trebuie sa aiba
timpi crescatori si aceleasi valori ca in Simview. Descarca **Export masuratori CSV**.
In `results/psim_*_partNNNN_samples.csv` verifica:

- `t_s`, `rpm`, `phase_current_a`, `vdc_v`, `f_ref_hz`: semnale PSIM;
- `rms_est_a`, `sync_rpm`, `speed_error_pct`, `status`: calcule Octave;
- timpul final si continuitatea esantioanelor intre segmente.

Contorul in crestere dovedeste receptia, nu garanteaza ca fiecare pas al solverului
a fost transmis. DLL esantioneaza nominal la 1 ms simulat si foloseste un
transport neblocant; pentru o verificare completa inspecteaza si golurile
din CSV si timpul final fata de rularea PSIM.

## 4. Pentru comenzi, in Comanda motor

**START/STOP confirmat** si referintele din panou reflecta confirmarea DLL.
Identificatorul tehnic ACK ramane in API (`control.psim.aplicat`).
Confirma separat in PSIM:

- OUT1 / F_TARGET → intrarea FREQ_RAMP; F_REF urmareste rampa.
- OUT2 / RUN → AND cu PWM_ENABLE; RUN=0 blocheaza autorizarea PWM.
- OUT3 / LOAD → intrarea de control LOAD_MECH; verifica unitatea si semnul
  in proprietatile LOAD_MECH.

ACK nu confirma cablarea, dinamica motorului sau cuplul efectiv. HMI nu afiseaza
LOAD cerut ca valoare masurata. Proprietatile ascunse ale blocului DLL si
scalarea LOAD_MECH nu pot fi validate din captura schemei.

## Daca numai VDC_LINK este nenul

Un DC-link incarcat nu confirma ca motorul este alimentat cu PWM. Inainte de a
diagnostica un fir, verifica in HMI ca DLL-ul este conectat, starea este
Pregatit si o comanda START cu frecventa pozitiva a fost acceptata. START la
0 Hz este refuzat.

Inaintea unei noi simulari, pregateste referintele in HMI: implicit 50 Hz / 5 Nm,
sau de exemplu 10 Hz / 0 Nm pentru un alt test. HMI-ul nu trimite automat
START la conectare; apasa START dupa ce DLL-ul indica starea Pregatit.
Daca F_REF ramane zero dupa rampa, verifica OUT1 -> FREQ_RAMP. Daca F_REF
creste dar curentul si RPM raman zero, verifica OUT2 -> AND_HMI_ENABLE,
PWM_ENABLE, impulsurile pe cele sase canale si conexiunile motorului in Simview.
Daca Simview arata semnale nenule dar CSV ramane zero, verifica firele si
ordinea IN1/IN2/IN4 ale DLL-ului. Confirmarea DLL singura nu valideaza cablarea.

Rularea din captura dureaza circa 2,2 s simulate. Daca termina inaintea comenzii,
controleaza setarea Total Time din PSIM pentru o fereastra de test adecvata.
HMI nu incetineste solverul si nu porneste simularea in locul F8.

## Daca nu sosesc date

- Verifica serviciul Octave si mesajul receptorului pe portul 5050 in consola.
- Verifica erorile PSIM la pornire si calea DLL x86. Foloseste noul DLL HMI,
  nu vechiul DLL care transmite numai telemetrie.
- Nu porni un al doilea receptor Octave pe 5050.
- Daca o simulare scurta a terminat foarte repede, verifica ultimul cadru si Inregistrari.
- MQTT deconectat nu impiedica acest traseu; datele PSIM ajung prin TCP, nu MQTT.

Pentru inspectie tehnica: `http://127.0.0.1:8765/api/stare` contine `receptie`,
`psim` si `control.psim`. `results/stare_receptie_psim.json` pastreaza
contorul si ultimul cadru. Executia nativa PSIM trebuie verificata cu circuitul tau;
testele automate folosesc transport izolat si o gazda DLL de test.

## Control cu rampe si protectii

Foloseste `bridge/psim_drive_control_plc.dll` in blocul existent cu 4 intrari si 3 iesiri. In STOP normal, OUT2 ramane activ pe durata decelerarii, apoi dezactiveaza PWM. Daca rotorul inca se misca, starea este COASTING; STOPPED cere sub 10 RPM stabil. Vezi [control_hmi.md](control_hmi.md) pentru secventa curenta.
