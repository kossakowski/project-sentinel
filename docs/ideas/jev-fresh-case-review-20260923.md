# Fresh Jev pipeline cases — review requested

All 40 articles are invented test inputs. Labels below were assigned by the assistant before inference. They are provisional until you review them. Each language follows the same ten scenario patterns with different locations. These are four related families, not forty independent samples.

## Expected behaviour

| Step | Source scenario | Expected action | Incident decision |
|---|---|---|---|
| 1 | active incursion | initial; urgency 9–10 | new |
| 2 | confirmation | silent; urgency 9–10 | duplicate |
| 3 | same missile first impact | update; urgency 9–10 | escalation |
| 4 | separate wave | initial; urgency 9–10 | new |
| 5 | wave neutralised | silent; urgency 1–4 | update |
| 6 | archived conventional drill | silent; urgency 1–3 | new |
| 7 | ongoing combat only inside Ukraine | silent; urgency 1–3 | new |
| 8 | local precautionary patrol | initial; urgency 5–6 | new |
| 9 | fabricated attack denied | silent; urgency 1–3 | new |
| 10 | explicitly hypothetical attack | silent; urgency 1–3 | new |

The first incident and separate new wave should each produce one simulated phone call. Confirmation should be silent. A first impact within the original incident should produce an update without another call for that incident. Resolved danger should be silent under the current low-urgency policy. The precautionary patrol should produce the configured awareness notification.

Country mapping: Polish sequence = Poland, then Latvian patrol; English = Latvia, then Lithuanian patrol; Russian = Lithuania, then Estonian patrol; Ukrainian = Estonia, then Polish patrol. Ukraine-only fighting never puts an attack in a monitored country.

## Exact inputs and labels

### j2-pl-01 (pl)

Wrogi pocisk leci nad Siedlcami w Polsce od 05:00. Nadal pozostaje nad polskim terytorium. Nie trafił dotąd w cel i nie wydano nakazu schronienia.

Expected: urgency 9–10; affected ['PL']; attack location ['PL']; protection none; status active; incident ['new']; notification initial.

### j2-pl-02 (pl)

Drugie źródło potwierdza ten sam pocisk obserwowany od 05:00 nad Siedlcami w Polsce. Nadal leci nad Polską; nie ma nowych trafień ani ostrzeżeń. To potwierdzenie wcześniejszej wiadomości, nie nowe zdarzenie.

Expected: urgency 9–10; affected ['PL']; attack location ['PL']; protection none; status active; incident ['duplicate']; notification silent.

### j2-pl-03 (pl)

Ten sam pocisk obserwowany od 05:00 nad Siedlcami w Polsce po raz pierwszy uderzył w magazyn. Są ranni. W ramach tego trwającego incydentu władze wydały pierwszy oficjalny nakaz schronienia mieszkańców Siedlec.

Expected: urgency 9–10; affected ['PL']; attack location ['PL']; protection official_warning; status active; incident ['escalation']; notification update.

### j2-pl-04 (pl)

Poprzedni incydent pod Siedlcami zakończył się. Odrębna nowa fala wrogich pocisków leci teraz nad Białą Podlaską w Polsce. To inne pociski i nowy incydent; nie wydano jeszcze ostrzeżenia dla mieszkańców.

Expected: urgency 9–10; affected ['PL']; attack location ['PL']; protection none; status active; incident ['new']; notification initial.

### j2-pl-05 (pl)

Nowa fala pocisków nad Białą Podlaską, opisana w poprzednim raporcie, została całkowicie zneutralizowana. Wszystkie pociski zniszczono; aktualnie nie ma zagrożenia. To zakończenie tego samego drugiego incydentu.

Expected: urgency 1–4; affected ['PL']; attack location ['PL']; protection none; status resolved; incident ['update']; notification silent.

### j2-pl-06 (pl)

Archivalny przegląd przypomina rutynowe ćwiczenia polskiej armii z 2019 roku. Nie używano broni jądrowej. Tekst nie opisuje rzeczywistego ataku ani żadnego obecnego zagrożenia.

Expected: urgency 1–3; affected []; attack location []; protection none; status historical; incident ['new']; notification silent.

### j2-pl-07 (pl)

Rosyjskie uderzenia na obiekty w środkowej Ukrainie nadal trwają. Cała walka odbywa się w Ukrainie, daleko od polskiej granicy. Polska i państwa bałtyckie nie zgłosiły lokalnych incydentów ani działań ochronnych.

Expected: urgency 1–3; affected []; attack location ['UA']; protection none; status active; incident ['new']; notification silent.

### j2-pl-08 (pl)

Łotwa poderwała myśliwce zapobiegawczo podczas trwających rosyjskich nalotów w środkowej Ukrainie. Łotewski patrol nadal trwa; nie stwierdzono naruszenia Łotwy ani nakazu schronienia. Litwa nie podjęła żadnych działań.

Expected: urgency 5–6; affected ['LV']; attack location ['UA']; protection precaution; status active; incident ['new']; notification initial.

### j2-pl-09 (pl)

Polskie władze zdementowały wpis o rzekomym ataku na Poznań. Żaden atak ani alarm dla mieszkańców nie wystąpił. Nie prowadzono działań ochronnych; wpis był całkowicie zmyślony.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-pl-10 (pl)

Autor analizuje hipotetyczny scenariusz: gdyby pociski zaatakowały Litwę, mogłaby nastąpić ewakuacja. Tekst wyraźnie stwierdza, że żaden opisany atak ani nakaz ewakuacji nie miał miejsca.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-en-01 (en)

A hostile missile has been flying above Rezekne in Latvia since 05:00. It remains over Latvian territory. No impact or resident shelter order has been reported.

Expected: urgency 9–10; affected ['LV']; attack location ['LV']; protection none; status active; incident ['new']; notification initial.

### j2-en-02 (en)

A second outlet confirms the same missile tracked over Rezekne in Latvia since 05:00. It is still airborne over Latvia. There are no new impacts or warnings; this confirms the previous report, not a separate event.

Expected: urgency 9–10; affected ['LV']; attack location ['LV']; protection none; status active; incident ['duplicate']; notification silent.

### j2-en-03 (en)

The same missile tracked over Rezekne in Latvia since 05:00 has now hit a warehouse for the first time. People are injured. Authorities issued the first official resident shelter order during this continuing incident.

Expected: urgency 9–10; affected ['LV']; attack location ['LV']; protection official_warning; status active; incident ['escalation']; notification update.

### j2-en-04 (en)

The earlier Rezekne incident has ended. A separate new wave of hostile missiles is now over Liepaja in Latvia. These are different missiles in a new incident; no resident warning has yet been issued.

Expected: urgency 9–10; affected ['LV']; attack location ['LV']; protection none; status active; incident ['new']; notification initial.

### j2-en-05 (en)

The new missile wave over Liepaja described in the previous report has been fully neutralised. Every missile was destroyed. There is no remaining danger; this closes that same second incident.

Expected: urgency 1–4; affected ['LV']; attack location ['LV']; protection none; status resolved; incident ['update']; notification silent.

### j2-en-06 (en)

An archive feature recalls routine Latvian military exercises in 2018. No nuclear weapons were involved. It describes neither a real attack nor a current threat.

Expected: urgency 1–3; affected []; attack location []; protection none; status historical; incident ['new']; notification silent.

### j2-en-07 (en)

Russian strikes on central Ukraine are continuing. All combat is inside Ukraine, far from monitored borders. Poland and the Baltic states report no local incidents or protective measures.

Expected: urgency 1–3; affected []; attack location ['UA']; protection none; status active; incident ['new']; notification silent.

### j2-en-08 (en)

Lithuania has scrambled fighters as a precaution during continuing Russian raids in central Ukraine. The Lithuanian patrol is ongoing; no Lithuanian incursion or civilian shelter order is reported. Latvia has taken no action.

Expected: urgency 5–6; affected ['LT']; attack location ['UA']; protection precaution; status active; incident ['new']; notification initial.

### j2-en-09 (en)

Latvian officials deny a fabricated claim of an attack on Jelgava. No attack, resident warning or protective operation occurred. The entire claim was false.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-en-10 (en)

The author discusses a hypothetical scenario: if missiles attacked Estonia, evacuation might follow. The article explicitly says that none of these attacks or evacuation orders has occurred.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-ru-01 (ru)

Вражеская ракета летит над Каунасом в Литве с 05:00. Она всё ещё находится над литовской территорией. Попаданий и приказа жителям укрыться пока не было.

Expected: urgency 9–10; affected ['LT']; attack location ['LT']; protection none; status active; incident ['new']; notification initial.

### j2-ru-02 (ru)

Второй источник подтверждает ту же ракету, которую наблюдают над Каунасом в Литве с 05:00. Она продолжает полёт над Литвой. Новых попаданий или предупреждений нет; это подтверждение прежнего сообщения, а не новое событие.

Expected: urgency 9–10; affected ['LT']; attack location ['LT']; protection none; status active; incident ['duplicate']; notification silent.

### j2-ru-03 (ru)

Та же ракета, наблюдаемая над Каунасом в Литве с 05:00, впервые попала в склад. Есть раненые. В рамках этого продолжающегося инцидента власти впервые официально приказали жителям Каунаса укрыться.

Expected: urgency 9–10; affected ['LT']; attack location ['LT']; protection official_warning; status active; incident ['escalation']; notification update.

### j2-ru-04 (ru)

Предыдущий инцидент в Каунасе завершён. Отдельная новая волна вражеских ракет сейчас летит над Клайпедой в Литве. Это другие ракеты и новый инцидент; предупреждения жителям пока нет.

Expected: urgency 9–10; affected ['LT']; attack location ['LT']; protection none; status active; incident ['new']; notification initial.

### j2-ru-05 (ru)

Новая волна ракет над Клайпедой, описанная в предыдущем сообщении, полностью нейтрализована. Все ракеты уничтожены, текущей угрозы нет. Это завершение того же второго инцидента.

Expected: urgency 1–4; affected ['LT']; attack location ['LT']; protection none; status resolved; incident ['update']; notification silent.

### j2-ru-06 (ru)

Архивная статья вспоминает обычные учения литовской армии в 2017 году. Ядерных сил не было. Статья не описывает реального нападения или нынешней угрозы.

Expected: urgency 1–3; affected []; attack location []; protection none; status historical; incident ['new']; notification silent.

### j2-ru-07 (ru)

Российские удары по объектам в центральной Украине продолжаются. Все боевые действия идут внутри Украины, далеко от границ наблюдаемых стран. В Польше и странах Балтии нет местных инцидентов или защитных мер.

Expected: urgency 1–3; affected []; attack location ['UA']; protection none; status active; incident ['new']; notification silent.

### j2-ru-08 (ru)

Эстония превентивно подняла истребители во время продолжающихся российских ударов в центральной Украине. Эстонское патрулирование продолжается; нарушений Эстонии и приказа жителям укрыться нет. Латвия и Литва не принимали мер.

Expected: urgency 5–6; affected ['EE']; attack location ['UA']; protection precaution; status active; incident ['new']; notification initial.

### j2-ru-09 (ru)

Литовские власти опровергли выдуманное сообщение об атаке на Шяуляй. Ни нападения, ни предупреждения населению, ни защитной операции не было. Всё сообщение было ложным.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-ru-10 (ru)

Автор разбирает гипотетический сценарий: если бы ракеты атаковали Польшу, могла бы начаться эвакуация. В статье прямо сказано, что ни одной из этих атак или эвакуационных команд в действительности не было.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-uk-01 (uk)

Ворожа ракета летить над Тарту в Естонії з 05:00. Вона досі перебуває над естонською територією. Влучань та наказу мешканцям перейти в укриття поки не було.

Expected: urgency 9–10; affected ['EE']; attack location ['EE']; protection none; status active; incident ['new']; notification initial.

### j2-uk-02 (uk)

Друге джерело підтверджує ту саму ракету, яку спостерігають над Тарту в Естонії з 05:00. Вона продовжує політ над Естонією. Нових влучань чи попереджень немає; це підтвердження попередньої звістки, а не нова подія.

Expected: urgency 9–10; affected ['EE']; attack location ['EE']; protection none; status active; incident ['duplicate']; notification silent.

### j2-uk-03 (uk)

Та сама ракета, яку спостерігають над Тарту в Естонії з 05:00, вперше влучила у склад. Є поранені. Під час цього триваючого інциденту влада вперше офіційно наказала мешканцям Тарту перейти в укриття.

Expected: urgency 9–10; affected ['EE']; attack location ['EE']; protection official_warning; status active; incident ['escalation']; notification update.

### j2-uk-04 (uk)

Попередній інцидент у Тарту завершився. Окрема нова хвиля ворожих ракет зараз летить над Пярну в Естонії. Це інші ракети та новий інцидент; попередження для мешканців поки немає.

Expected: urgency 9–10; affected ['EE']; attack location ['EE']; protection none; status active; incident ['new']; notification initial.

### j2-uk-05 (uk)

Нову хвилю ракет над Пярну, описану в попередньому повідомленні, повністю нейтралізовано. Усі ракети знищено, поточної загрози немає. Це завершення того самого другого інциденту.

Expected: urgency 1–4; affected ['EE']; attack location ['EE']; protection none; status resolved; incident ['update']; notification silent.

### j2-uk-06 (uk)

Архівна стаття згадує звичайні навчання естонської армії у 2016 році. Ядерної зброї не було. Стаття не описує реального нападу або нинішньої загрози.

Expected: urgency 1–3; affected []; attack location []; protection none; status historical; incident ['new']; notification silent.

### j2-uk-07 (uk)

Російські удари по об’єктах у центральній Україні тривають. Усі бойові дії відбуваються всередині України, далеко від кордонів країн спостереження. Польща та країни Балтії не повідомляли про місцеві інциденти чи захисні заходи.

Expected: urgency 1–3; affected []; attack location ['UA']; protection none; status active; incident ['new']; notification silent.

### j2-uk-08 (uk)

Польща підняла винищувачі як запобіжний захід під час триваючих російських нальотів у центральній Україні. Польське патрулювання триває; порушення Польщі та наказу мешканцям перейти в укриття немає. Литва й Латвія не вживали заходів.

Expected: urgency 5–6; affected ['PL']; attack location ['UA']; protection precaution; status active; incident ['new']; notification initial.

### j2-uk-09 (uk)

Естонська влада спростувала вигадане повідомлення про атаку на Нарву. Нападу, попередження населенню та захисної операції не було. Усе повідомлення було неправдивим.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.

### j2-uk-10 (uk)

Автор розглядає гіпотетичний сценарій: якби ракети атакували Латвію, могла б початися евакуація. У статті прямо сказано, що жодної з цих атак або команд на евакуацію насправді не було.

Expected: urgency 1–3; affected []; attack location []; protection none; status unclear; incident ['new']; notification silent.
