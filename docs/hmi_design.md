# HMI — decizii de proiectare și verificare

Redesign implementat la 13 octombrie 2026, peste infrastructura existentă.

## Audit și decizii

- Starea motorului, comunicația și alarmele au o bandă comună; procesele pornite nu sunt echivalate cu motor în funcțiune. Antetul conține doar numele aplicației.
- Cele cinci măsurători sunt grupate uniform. RMS-ul este marcat ca estimare; detaliile calculelor sunt în Diagnostic.
- Scara graficului se recalcula la fiecare actualizare. Autoscalarea păstrează intervalul și îl extinde la depășire; reîncadrarea și intervalele fixe sunt explicite. Depășirea unei scări fixe este semnalată. Cursorul urmărește un eșantion real, inclusiv prin tastatură.
- Graficele separă valorile lipsă și golurile DATA_GAP primite din diagnostic. Nu deduc goluri din distanța dintre punctele agregate, care poate varia normal.
- Selectoarele și tabelele erau reconstruite la interogări neschimbate. Acum își păstrează nodurile, focusul și selecția; graficul neschimbat nu recopiază bufferul de pixeli.
- Alarmele au stare explicită, ordine după severitate și diferențiere între activ și istoric. Evenimentele controlerului sunt distincte de cele ale monitorizării.
- Înregistrările includ jurnalul, sursa, intervalul afișat, închiderea confirmată/neconfirmată și rândurile invalide. Fișierul CSV exportat rămâne integral; graficul reprezintă fereastra recentă disponibilă în memoria limitată a backendului.

Tema luminoasă folosește Segoe UI, cifre tabulare, suprafețe neutre, un accent verde-petrol și culori semantice pentru defecte/avertizări. STOP este o comandă normală de decelerare, cu formă și etichetă distincte; descrierea este disponibilă la trecerea cursorului. Mesajele din panoul de comandă explică interblocările și confirmă solicitările; stările normale nu au instrucțiuni repetitive. Spațiile rezervate feedbackului reduc deplasarea comenzilor.

## Compatibilitate

Circuitul, DLL-ul, PWM-ul, protecțiile, algoritmii Octave și MQTT nu au fost modificate. Cele patru referințe și acțiunile START/STOP/RESET folosesc același endpoint. Confirmarea comenzii și starea motorului sunt prezentate separat, exclusiv din feedback.

Modificări backend limitate: servirea fișierului `charts.js` și expunerea câmpului `abatere_pct`, citit din coloana Octave existentă `speed_error_pct`. Câmpurile API anterioare și CSV-urile rămân compatibile. Nu există un model dinamic independent sincronizat în HMI; secțiunea Octave afișează numai calculele existente, fără MAE/RMSE inventate.

## Verificări

- Testele Node acoperă autorizările, comenzile în așteptare/refuzate/expirate, STOP în timpul unei comenzi, rampele, pierderea HTTP, alarmele, înregistrările, autoscalarea, datele lipsă și cursorul graficului.
- Testele Python acoperă controlul, contractele de date, integrarea transportului și retenția înregistrărilor.
- Verificarea vizuală anterioară a acoperit Operare, Diagnostic și Înregistrări, inclusiv cursorul, scările graficului și păstrarea editării câmpurilor la actualizarea datelor.
- Rezoluțiile verificate anterior au fost 1366×768, 1920×1080 și 2560×1440; comenzile START/STOP au rămas accesibile la 1366×768 cu secțiunea Rampe deschisă.
- Nicio campanie nouă PSIM și nicio comandă trimisă motorului pentru redesign. Stările de control au fost testate izolat, nu printr-o validare electrică nouă.

Capturile HMI pentru documentația publică nu sunt încă adăugate; locurile recomandate sunt descrise în README. Certificarea WCAG/ISA sau validarea fizică a protecțiilor nu rezultă din aceste verificări.

## Fișiere

`dashboard/index.html`, `dashboard/app.css`, `dashboard/app.js`, `dashboard/charts.js`, `dashboard/server.py`, `application/data_store.py`, `tests/test_hmi_ui.js`, `tests/test_hmi_charts.js`, `tests/test_data_contracts.py`, `README.md` și acest document.
