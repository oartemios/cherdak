function speechGapBefore(index, gap, headings = []) {
  return index ? gap + (headings.includes(index - 1) ? 0.55 : 0) : 0;
}

export function speechTimeline(durations, gap, headings) {
  const entries = [];
  let end = 0;
  for (const [index, duration] of durations.entries()) {
    if (!(duration > 0)) break;
    const start = end + speechGapBefore(index, gap, headings);
    end = start + duration;
    entries.push({start, end});
  }
  return entries;
}

export function findSpeechPosition(timeline, time) {
  const found = timeline.findIndex(entry => time < entry.end);
  const index = found === -1 ? timeline.length - 1 : found;
  const {start, end} = timeline[index];
  const offset = Math.max(0, Math.min(time - start, end - start - 0.001));
  return {index, offset};
}

export function scheduleSpeechBuffer(ctx, buffer, start, offset, mode) {
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  const duration = buffer.duration - offset;
  const end = start + duration;
  if (mode === 'improved') {
    const gain = ctx.createGain();
    const fade = Math.min(0.008, duration / 2);
    source.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(1, start + fade);
    gain.gain.setValueAtTime(1, end - fade);
    gain.gain.linearRampToValueAtTime(0, end);
  } else {
    source.connect(ctx.destination);
  }
  source.start(start, offset);
  return {source, end};
}

export function initSpeech({article, kind, path, data}) {
const lifecycle = new AbortController();
const voiceChoice=document.querySelector('#voice-choice'),listenPanel=document.querySelector('#listen-panel'),clonePanel=document.querySelector('#clone-settings');function setSpeechMode(create) {
  listenPanel.hidden = create;
  clonePanel.hidden = !create;
  document.querySelector('#return-to-listen').hidden = !create;
}
document.querySelector('#listen-mode').onclick = () => {
  setSpeechMode(false);
  voiceChoice.focus();
};
let voiceProfiles=[];const voiceParent=document.querySelector('#voice-parent'),speechStyle=document.querySelector('#speech-style');function updateSpeechStyle(){let id=voiceChoice.value.startsWith('clone:')?voiceChoice.value.slice(6):null,base=voiceProfiles.find(p=>p.id===id);document.querySelector('#speech-style-setting').hidden=!base;if(!base)return;let parent=base.parent_id||base.id,variants=voiceProfiles.filter(p=>p.id===parent||p.parent_id===parent),previous=localStorage.getItem('speechStyle:'+parent),labels={neutral:'Обычная',whisper:'Шёпот',joy:'Радость',anxiety:'Тревога',anger:'Раздражение'};speechStyle.replaceChildren();for(let p of variants){let o=document.createElement('option');o.value=p.id;o.textContent=(labels[p.emotion]||'Обычная')+' · '+p.name;speechStyle.append(o)}speechStyle.value=variants.some(p=>p.id===previous)?previous:base.id}speechStyle.onchange=()=>{let id=voiceChoice.value.slice(6),base=voiceProfiles.find(p=>p.id===id);if(base)localStorage.setItem('speechStyle:'+(base.parent_id||base.id),speechStyle.value);restoreVoiceJob()};function effectiveVoice(){return voiceChoice.value.startsWith('clone:')&&speechStyle.value?'clone:'+speechStyle.value:voiceChoice.value}async function refreshVoices(selected){try{let r=await fetch('/api/voices');if(!r.ok)throw Error();let profiles=await r.json();if(lifecycle.signal.aborted)return;let group=document.querySelector('#custom-voices');voiceProfiles=profiles;const addVoice=group.querySelector('option[value="add-voice"]');group.replaceChildren(addVoice);
const f5Group = document.querySelector('#f5-voices');
f5Group?.replaceChildren(f5Group.querySelector('option[value="f5:add-voice"]'));
voiceParent.replaceChildren();let none=document.createElement('option');none.value='';none.textContent='Создать отдельный голос';voiceParent.append(none);for(let p of profiles.filter(p=>!p.parent_id)){let option=document.createElement('option');option.value=p.id;option.textContent=p.name;voiceParent.append(option)}for(let p of profiles){let o=document.createElement('option');o.value='clone:'+p.id;let labels={joy:'радость',anxiety:'тревога',anger:'раздражение',whisper:'шёпот'};o.textContent=p.name+(p.origin==='synthetic'?' · синтетический':'')+(labels[p.emotion]?' · '+labels[p.emotion]:'');o.dataset.voiceName=p.name;group.append(o);
if (f5Group) {
  const option = o.cloneNode(true);
  option.value = 'f5:' + p.id;
  f5Group.append(option);
}
}let desired=selected||localStorage.getItem('selectedVoice');if(desired&&[...voiceChoice.options].some(o=>o.value===desired))voiceChoice.value=desired}catch(e){document.querySelector('#speech-status').textContent='Не удалось загрузить список голосов'}}const syntheticKinds = [...document.querySelectorAll('input[name="synthetic-kind"]')];
const syntheticAge = document.querySelector('#synthetic-age');
const storedKind = localStorage.getItem('syntheticKind');
for (const input of syntheticKinds) input.checked = input.value === (['female', 'male', 'child'].includes(storedKind) ? storedKind : 'female');
function selectedSyntheticKind() {
  return syntheticKinds.find(input => input.checked).value;
}
function updateSyntheticAge(reset = false) {
  const kind = selectedSyntheticKind();
  const child = kind === 'child';
  const min = child ? 5 : 18;
  const max = child ? 17 : 100;
  syntheticAge.min = min;
  syntheticAge.max = max;
  const age = Number(syntheticAge.value);
  if (reset || !Number.isInteger(age) || age < min || age > max) syntheticAge.value = child ? 10 : 30;
  localStorage.setItem('syntheticKind', kind);
  localStorage.setItem('syntheticAge', syntheticAge.value);
}
syntheticAge.value = localStorage.getItem('syntheticAge') || '30';
updateSyntheticAge();
for (const input of syntheticKinds) input.onchange = () => { updateSyntheticAge(true); restoreVoiceJob(); };
syntheticAge.onchange = () => { updateSyntheticAge(); restoreVoiceJob(); };
function syntheticOptions(engine) {
  if (engine !== 'synthetic') return {};
  updateSyntheticAge();
  return {synthetic_kind: selectedSyntheticKind(), synthetic_age: Number(syntheticAge.value)};
}
function selectedVoiceSettings(value = effectiveVoice(), speed = Number(speedControl.value)) {
  const [engine, voice] = value.split(':');
  switch (engine) {
    case 'f5':
    case 'clone': return {engine, profile: voice};
    case 'local': return {engine, local_voice: voice, speed};
    case 'openai': return {engine, voice};
    default: return {engine, ...syntheticOptions(engine)};
  }
}
const engineChoice = document.querySelector('#speech-engine');
function engineForVoice(value) {
  return value === 'add-voice' ? 'clone' : value.split(':')[0];
}
engineChoice.onchange = () => {
    const options = [...voiceChoice.options].filter(option => engineForVoice(option.value) === engineChoice.value);
    const preferred = localStorage.getItem('speechVoice:' + engineChoice.value);
    const voice = options.find(option => option.value === preferred && !['add-voice', 'f5:add-voice'].includes(option.value))
      ?? options.find(option => !['add-voice', 'f5:add-voice'].includes(option.value))
      ?? options[0];
    if (!voice) return;
    voiceChoice.value = voice.value;
    voiceChoice.onchange();
};
function updateRenameButton() {
  const engine = engineForVoice(voiceChoice.value);
  engineChoice.value = engine;
  for (const group of voiceChoice.querySelectorAll('optgroup')) {
    group.hidden = ![...group.children].some(option => engineForVoice(option.value) === engine);
    group.disabled = group.hidden;
  }
  document.querySelector('#speech-voice-row').hidden = engine === 'synthetic';
  document.querySelector('#synthetic-settings').hidden = engine !== 'synthetic';
  document.querySelector('#speed-setting').hidden = engine !== 'local';
  document.querySelector('#rename-voice').hidden = engine !== 'clone';
  document.querySelector('#sentence-setting').hidden = !['clone', 'synthetic', 'f5'].includes(engine);
  updateSpeechStyle();
}
let newVoiceEngine = 'clone';
voiceChoice.onchange = () => {
  if (['add-voice', 'f5:add-voice'].includes(voiceChoice.value)) {
    newVoiceEngine = engineForVoice(voiceChoice.value);
    const previous = localStorage.getItem('selectedVoice');
    voiceChoice.value = [...voiceChoice.options].some(option => option.value === previous && previous !== 'add-voice')
      ? previous : 'local:ruslan';
    updateRenameButton();
    setSpeechMode(true);
    document.querySelector('#listen-mode').focus();
    return;
  }
  localStorage.setItem('selectedVoice', voiceChoice.value);
  localStorage.setItem('speechVoice:' + engineForVoice(voiceChoice.value), voiceChoice.value);
  updateRenameButton();
  restoreVoiceJob();
};
document.querySelector('#rename-voice').onclick=async()=>{let selected=voiceChoice.value,id=selected.slice(6),old=voiceChoice.selectedOptions[0]?.dataset.voiceName||voiceChoice.selectedOptions[0]?.textContent;let name=prompt('Новое название голоса',old);if(name===null)return;name=name.trim();if(!name||name.length>80){document.querySelector('#speech-status').textContent='Введите название длиной до 80 символов.';return}try{let r=await fetch('/api/voice-rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,name})});if(!r.ok)throw Error();await refreshVoices(selected);updateRenameButton();document.querySelector('#speech-status').textContent='Название сохранено.'}catch{document.querySelector('#speech-status').textContent='Не удалось переименовать голос.'}};const storedVoice = localStorage.getItem('selectedVoice');
if ([...voiceChoice.options].some(option => option.value === storedVoice)) voiceChoice.value = storedVoice;
updateRenameButton();refreshVoices().then(() => {updateRenameButton(); restoreVoiceJob()});const sentenceSetting=document.querySelector('#sentence-count');sentenceSetting.value=localStorage.getItem('speechSentences')||'1';sentenceSetting.onchange=()=>localStorage.setItem('speechSentences',sentenceSetting.value);let recordedVoice=null,recorder=null,recordStream=null,recordTimer=null,previewUrl=null;const recordButton=document.querySelector('#record-voice'),stopRecordButton=document.querySelector('#stop-recording'),voiceStatus=document.querySelector('#voice-status'),voicePreview=document.querySelector('#voice-preview');function wavEncode(buffer){let n=buffer.length,rate=buffer.sampleRate,channels=buffer.numberOfChannels,data=new ArrayBuffer(44+n*2),view=new DataView(data);function str(offset,value){for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i))}str(0,'RIFF');view.setUint32(4,36+n*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,n*2,true);for(let i=0;i<n;i++){let sample=0;for(let c=0;c<channels;c++)sample+=buffer.getChannelData(c)[i]/channels;sample=Math.max(-1,Math.min(1,sample));view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true)}return new Blob([data],{type:'audio/wav'})}recordButton.onclick=async()=>{try{if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('Браузер не поддерживает запись с микрофона');recordStream=await navigator.mediaDevices.getUserMedia({audio:true});if(lifecycle.signal.aborted){recordStream.getTracks().forEach(t=>t.stop());return}let parts=[];recorder=new MediaRecorder(recordStream);recorder.ondataavailable=e=>{if(e.data.size)parts.push(e.data)};recorder.onstop=async()=>{clearTimeout(recordTimer);recordStream.getTracks().forEach(t=>t.stop());if(lifecycle.signal.aborted)return;recordButton.classList.remove('is-active');recordButton.setAttribute('aria-pressed','false');recordButton.disabled=false;stopRecordButton.disabled=true;try{let context=new AudioContext();let decoded=await context.decodeAudioData(await new Blob(parts).arrayBuffer());recordedVoice=wavEncode(decoded);await context.close();if(lifecycle.signal.aborted)return;if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(recordedVoice);voicePreview.src=previewUrl;voicePreview.hidden=false;document.querySelector('#voice-file').value='';voiceStatus.textContent='Запись готова ('+decoded.duration.toFixed(1)+' с). Введите текст и сохраните образец.'}catch{voiceStatus.textContent='Не удалось обработать запись'}};recorder.start();recordButton.classList.add('is-active');recordButton.setAttribute('aria-pressed','true');recordButton.disabled=true;stopRecordButton.disabled=false;voiceStatus.textContent='Идёт запись… максимум 60 секунд';recordTimer=setTimeout(()=>{if(recorder?.state==='recording')recorder.stop()},60000)}catch(e){if(recordStream)recordStream.getTracks().forEach(t=>t.stop());voiceStatus.textContent='Не удалось начать запись. Проверьте разрешение на микрофон.'}};stopRecordButton.onclick=()=>{if(recorder?.state==='recording')recorder.stop()};document.querySelector('#voice-file').onchange=()=>{recordedVoice=null;if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;voicePreview.hidden=true};window.addEventListener('beforeunload',()=>{if(recordStream)recordStream.getTracks().forEach(t=>t.stop());if(previewUrl)URL.revokeObjectURL(previewUrl)},{signal:lifecycle.signal});document.querySelector('#transcribe-voice').onclick=async()=>{let button=document.querySelector('#transcribe-voice'),file=recordedVoice||document.querySelector('#voice-file').files[0];if(!file){voiceStatus.textContent='Сначала запишите голос или выберите WAV-файл';return}if(file.size>20000000){voiceStatus.textContent='Файл слишком большой';return}button.disabled=true;voiceStatus.textContent='Распознаю запись локально…';try{let audio=await new Promise((resolve,reject)=>{let reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});let r=await fetch('/api/transcribe-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audio})});if(!r.ok)throw Error();let result=await r.json();document.querySelector('#voice-transcript').value=result.text;voiceStatus.textContent='Проверьте текст и исправьте ошибки перед сохранением.'}catch{voiceStatus.textContent='Не удалось распознать запись. Проверьте WAV-файл и доступность модели.'}finally{button.disabled=false}};document.querySelector('#save-voice').onclick=async()=>{let file=recordedVoice||document.querySelector('#voice-file').files[0],transcript=document.querySelector('#voice-transcript').value.trim(),name=document.querySelector('#voice-name').value.trim(),emotion=document.querySelector('#voice-emotion').value,status=document.querySelector('#voice-status');if(!file||!transcript||!name){status.textContent='Укажите название, запись и текст образца';return}if(file.size>20000000){status.textContent='Файл слишком большой';return}try{let audio=await new Promise((resolve,reject)=>{let reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});let r=await fetch('/api/voice-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audio,transcript,name,emotion,parent_id:voiceParent.value||null})});if(!r.ok)throw Error();let saved=await r.json();let selected=newVoiceEngine==='f5'?'f5:'+saved.id:'clone:'+(saved.parent_id||saved.id);if(saved.parent_id)localStorage.setItem('speechStyle:'+saved.parent_id,saved.id);await refreshVoices(selected);updateRenameButton();localStorage.setItem('selectedVoice',selected);localStorage.setItem('speechVoice:'+newVoiceEngine,selected);newVoiceEngine='clone';restoreVoiceJob();setSpeechMode(false);document.querySelector('#speech-status').textContent='Голос «'+saved.name+'» сохранён и выбран.';document.querySelector('#voice-name').value='';document.querySelector('#voice-emotion').value='neutral';document.querySelector('#voice-transcript').value='';document.querySelector('#voice-file').value='';recordedVoice=null;voicePreview.hidden=true;}catch{status.textContent='Не удалось сохранить: нужен WAV PCM длительностью 2–60 секунд'}};let speedControl=document.querySelector('#speech-speed');speedControl.value=localStorage.getItem('speechSpeed')||'1';function updateSpeechSpeed(){document.querySelector('#speed-value').textContent=Number(speedControl.value).toFixed(1)+'×'}speedControl.oninput=()=>{localStorage.setItem('speechSpeed',speedControl.value);updateSpeechSpeed()};speedControl.onchange=()=>restoreVoiceJob();updateSpeechSpeed();let speechStatus=document.querySelector('#speech-status'),generation=0,playerState='idle',jobState='idle',playbackIndex=0,playbackTotal=0,playbackContext=null,playbackSources=[],playbackSchedule=[],playbackTimer=null,playbackAbort=null;const playbackBar = document.querySelector('#playback-bar');
let seekSession = null, scrubbing = false;

function formatPlaybackTime(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  return Math.floor(value / 60) + ':' + String(value % 60).padStart(2, '0');
}
function updatePlaybackClock(completed) {
  const last = playbackSchedule.at(-1);
  const readyDuration = seekSession?.timeline.at(-1)?.end ?? 0;
  const totalDuration = seekSession
    ? (seekSession.timeline.length === playbackTotal ? readyDuration : null)
    : (last ? last.end - playbackSchedule[0].start : null);
  let elapsed = seekSession?.position ?? 0;
  if (completed && totalDuration !== null) {
    elapsed = totalDuration;
  } else if (playbackContext) {
    for (const item of playbackSchedule) {
      if (playbackContext.currentTime < item.start) break;
      const position = item.position ?? item.start - playbackSchedule[0].start;
      elapsed = position + Math.min(item.end, playbackContext.currentTime) - item.start;
    }
  }
  if (seekSession) seekSession.position = elapsed;
  if (!scrubbing) {
    playbackBar.max = readyDuration || totalDuration || 0;
    playbackBar.value = elapsed;
    showPlaybackPosition(elapsed);
  }
  playbackBar.disabled = !readyDuration;
  document.querySelector('#playback-duration').textContent = totalDuration === null ? '—' : formatPlaybackTime(totalDuration);
}

function showPlaybackPosition(seconds) {
  const time = formatPlaybackTime(seconds);
  document.querySelector('#playback-elapsed').textContent = time;
  playbackBar.setAttribute('aria-valuetext', time);
}

playbackBar.oninput = () => {
  scrubbing = true;
  showPlaybackPosition(Number(playbackBar.value));
};
playbackBar.onchange = () => {
  scrubbing = false;
  if (!seekSession || playbackBar.disabled) return;
  void playFinal(false, {session: seekSession, time: Number(playbackBar.value), paused: playerState === 'paused'});
};
playbackBar.onpointercancel = () => {
  scrubbing = false;
  updatePlaybackClock(false);
};

function updatePlaybackProgress(completed=false){if(!playbackTotal)return;updatePlaybackClock(completed);let fraction=0;if(playbackContext&&!completed){let now=playbackContext.currentTime;for(const item of playbackSchedule)if(now>=item.start){playbackIndex=item.index;fraction=Math.min(1,Math.max(0,(now-item.start)/(item.end-item.start)))}else break}let percent=completed?100:Math.min(100,Math.round((playbackIndex+fraction)/playbackTotal*100));document.querySelector('#playback-percent').textContent=percent+'%';document.querySelector('#playback-detail').textContent=completed?'Прослушано '+playbackTotal+' из '+playbackTotal+' фрагментов':'Фрагмент '+(playbackIndex+1)+' из '+playbackTotal+' · завершено '+playbackIndex;document.querySelector('#playback-progress').hidden=false}const playbackMode=document.querySelector('#speech-playback-mode'),speechGap=document.querySelector('#speech-gap');playbackMode.value=localStorage.getItem('speechPlaybackMode')||'improved';speechGap.value=localStorage.getItem('speechGap')||'0';playbackMode.onchange=()=>localStorage.setItem('speechPlaybackMode',playbackMode.value);speechGap.onchange=()=>localStorage.setItem('speechGap',speechGap.value);function processSpeech(buffer){return playbackMode.value==='legacy'?normalizeSpeech(buffer):buffer}function normalizeSpeech(buffer){let sum=0,count=0,peak=0;for(let c=0;c<buffer.numberOfChannels;c++){let samples=buffer.getChannelData(c);for(let i=0;i<samples.length;i++){let v=Math.abs(samples[i]);if(v>peak)peak=v;if(v>=0.012){sum+=v*v;count++}}}if(!count||!peak)return buffer;let rms=Math.sqrt(sum/count),gain=Math.min(2,0.14/rms,0.95/peak);for(let c=0;c<buffer.numberOfChannels;c++){let samples=buffer.getChannelData(c);for(let i=0;i<samples.length;i++)samples[i]*=gain}return buffer}function updateSpeechButtons(){let prepare=document.querySelector('#prepare-speech'),play=document.querySelector('#speak'),stop=document.querySelector('#stop');let preparing=['starting','queued','generating','pausing'].includes(jobState);let pauseGeneration=document.querySelector('#pause-generation');pauseGeneration.disabled=!['queued','generating'].includes(jobState);pauseGeneration.classList.toggle('is-active',jobState==='pausing');pauseGeneration.title=jobState==='pausing'?'Остановка после текущего фрагмента':'Остановить генерацию после текущего фрагмента';prepare.classList.toggle('is-active',preparing);prepare.setAttribute('aria-pressed',String(preparing));prepare.title=preparing?'Подготовка аудио':jobState==='paused'?'Продолжить генерацию':'Подготовить аудио';prepare.textContent=prepare.title;prepare.setAttribute('aria-label',prepare.title);prepare.disabled=preparing;let active=playerState==='playing'||playerState==='waiting';play.classList.toggle('is-active',active);play.setAttribute('aria-pressed',String(active));play.textContent=playerState==='playing'?'Ⅱ':'▶';play.title=playerState==='waiting'?'Ожидание аудио':playerState==='playing'?'Пауза':playerState==='paused'?'Продолжить воспроизведение':'Слушать';play.setAttribute('aria-label',play.title);play.disabled=playerState==='waiting';stop.disabled=playerState==='idle' }updateSpeechButtons();function stopAudio(){if(typeof stopFragmentPreview==='function')stopFragmentPreview();generation++;if(playbackAbort)playbackAbort.abort();playbackAbort=null;if(playbackTimer)clearInterval(playbackTimer);playbackTimer=null;for(let source of playbackSources){try{source.stop()}catch(e){}}playbackSources=[];playbackSchedule=[];seekSession=null;scrubbing=false;updatePlaybackClock(false);if(playbackContext){playbackContext.close().catch(()=>{});playbackContext=null}playerState='idle';updateSpeechButtons();speechStatus.textContent=''}let progressKey;const progressBox=document.querySelector('#generation-progress'),progressBar=document.querySelector('#generation-bar');let progressTimer=null,trackedJob=null;function stopTracking(){if(progressTimer)clearTimeout(progressTimer);progressTimer=null;trackedJob=null;document.querySelector('#save-synthetic-voice').disabled=true;document.querySelector('#save-synthetic-voice').hidden=true}function trackSpeechJob(id){stopTracking();trackedJob=id;localStorage.setItem(progressKey,id);progressBox.hidden=false;if(fragmentMode)refreshFragmentMode();async function poll(){if(trackedJob!==id)return;try{let r=await fetch('/api/speech-job?'+new URLSearchParams({id}));if(trackedJob!==id)return;if(r.status===404){localStorage.removeItem(progressKey);progressBox.hidden=true;stopTracking();jobState='idle';updateSpeechButtons();refreshFinalVersion();return}if(!r.ok)throw Error();let state=await r.json();if(trackedJob!==id)return;jobState=state.state;const saveReference=document.querySelector('#save-synthetic-voice');saveReference.disabled=!state.synthetic_reference_ready;saveReference.hidden=!state.synthetic_reference_ready;updateSpeechButtons();let percent=state.total?Math.round(100*state.ready/state.total):0;progressBar.value=percent;document.querySelector('#generation-percent').textContent=percent+'%';document.querySelector('#generation-label').textContent=state.state==='complete'?'Аудио готово':state.state==='error'?'Ошибка генерации':state.state==='cancelled'?'Генерация отменена':state.state==='superseded'?'Версия заменена':state.state==='queued'?'В очереди':state.state==='pausing'?'Остановка после текущего фрагмента':state.state==='paused'?'Генерация остановлена':'Генерация аудио';document.querySelector('#generation-detail').textContent=state.ready+' из '+state.total+' фрагментов'+(state.state==='error'&&state.error?' · '+state.error:'');if(state.state==='complete')refreshFinalVersion();if(['complete','error','cancelled','paused','superseded'].includes(state.state))return;progressTimer=setTimeout(poll,1500)}catch{if(trackedJob===id){document.querySelector('#generation-detail').textContent='Нет связи с сервером. Повторная попытка…';progressTimer=setTimeout(poll,3000)}}}poll()}let fragmentMode=false,fragmentParts=[],fragmentMenu=null,fragmentVersion=0,fragmentJob=null;const fragmentButton=document.querySelector('#fragment-mode'),fragmentStatus=document.querySelector('#fragment-status');function closeFragmentMenu(){if(fragmentMenu){fragmentMenu.remove();fragmentMenu=null}article.querySelectorAll('.fragment-segment.selected').forEach(el=>el.classList.remove('selected'))}function clearFragmentMarks(){closeFragmentMenu();article.querySelectorAll('.fragment-segment').forEach(el=>el.replaceWith(...el.childNodes));article.normalize()}function buildFragmentMarks(parts){clearFragmentMarks();let walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT),node,plain='',mapping=[],previousBlock=null;function addSpace(){if(plain&&!plain.endsWith(' ')){plain+=' ';mapping.push(null)}}while(node=walker.nextNode()){let block=node.parentElement.closest('p,h1,h2,h3,h4,h5,h6,li,blockquote,pre');if(previousBlock&&block!==previousBlock)addSpace();previousBlock=block;for(let i=0;i<node.data.length;i++){let ch=node.data[i];if(/\s/.test(ch)){addSpace();continue}plain+=ch;mapping.push({node,offset:i})}}let offset=0,perNode=new Map(),matched=0;for(const part of parts){let text=part.text.replace(/\s+/g,' ').trim();let begin=plain.indexOf(text,offset);if(begin<0)continue;let end=begin+text.length;offset=end;matched++;for(let i=begin;i<end;i++){let ref=mapping[i];if(!ref)continue;let list=perNode.get(ref.node)||[];let last=list[list.length-1];if(last&&last.index===part.index&&last.end<=ref.offset)last.end=ref.offset+1;else list.push({start:ref.offset,end:ref.offset+1,index:part.index,ready:part.ready});perNode.set(ref.node,list)}}for(const [textNode,segments] of perNode){segments.sort((a,b)=>b.start-a.start);for(const part of segments){textNode.splitText(part.end);let middle=textNode.splitText(part.start);let mark=document.createElement('span');mark.className='fragment-segment'+(part.ready?'':' unavailable');mark.dataset.fragment=part.index;mark.tabIndex=0;mark.setAttribute('role','button');mark.setAttribute('aria-label','Фрагмент '+(part.index+1)+'. Открыть действия');middle.parentNode.replaceChild(mark,middle);mark.append(middle)}}return matched}async function refreshFragmentMode(){let version=++fragmentVersion,id=trackedJob;clearFragmentMarks();if(!fragmentMode)return;if(!id){fragmentStatus.textContent='Сначала подготовьте аудио для этого текста.';return}fragmentStatus.textContent='Загрузка фрагментов…';try{let response=await fetch('/api/speech-parts?'+new URLSearchParams({id}));if(!response.ok)throw Error();let parts=await response.json();if(!fragmentMode||version!==fragmentVersion||id!==trackedJob)return;fragmentParts=parts;fragmentJob=id;let count=buildFragmentMarks(parts);fragmentStatus.textContent=count===parts.length?'Выберите фрагмент и откройте его меню.':('Найдено '+count+' из '+parts.length+' фрагментов. Текст мог измениться после генерации.')}catch{if(fragmentMode&&version===fragmentVersion)fragmentStatus.textContent='Не удалось загрузить фрагменты. Перезапустите сервер.'}}fragmentButton.onclick=()=>{fragmentMode=!fragmentMode;fragmentButton.classList.toggle('active',fragmentMode);fragmentButton.setAttribute('aria-pressed',String(fragmentMode));fragmentButton.textContent=fragmentMode?'✓ Завершить редактирование':'✎ Редактировать фрагменты';if(fragmentMode)refreshFragmentMode();else{fragmentVersion++;clearFragmentMarks();fragmentStatus.textContent=''}};let fragmentPreview=null;function stopFragmentPreview(){if(fragmentPreview){let current=fragmentPreview;fragmentPreview=null;current.abort?.abort();try{current.source?.stop()}catch(e){}if(current.context.state!=='closed')current.context.close().catch(()=>{});current.onstop?.()}}async function openFragmentMenu(mark){if(!fragmentMode)return;let index=Number(mark.dataset.fragment),part=fragmentParts.find(p=>p.index===index),id=fragmentJob;if(!part||!id)return;closeFragmentMenu();article.querySelectorAll('.fragment-segment').forEach(el=>{if(Number(el.dataset.fragment)===index)el.classList.add('selected')});let menu=document.createElement('div');menu.className='fragment-context';menu.setAttribute('role','menu');let title=document.createElement('strong');title.textContent='Фрагмент '+(index+1);let status=document.createElement('small'),controls=document.createElement('div');controls.className='fragment-actions';function icon(symbol,label,className){let button=document.createElement('button');button.type='button';button.className='fragment-action '+className;button.textContent=symbol;button.title=label;button.setAttribute('aria-label',label);button.setAttribute('role','menuitem');return button}let play=icon('▶','Прослушать фрагмент','fragment-play'),stop=icon('■','Остановить воспроизведение или перегенерацию','fragment-stop'),regenerate=icon('↻','Перегенерировать фрагмент','fragment-regenerate');function updateMenu(){let state=part.repair?.state,busy=['queued','generating','stopping'].includes(state);status.textContent=!part.ready?'Ещё не готов':state==='queued'?'В очереди':state==='generating'?'Перегенерация…':state==='stopping'?'Остановка…':state==='cancelled'?'Остановлено; прежнее аудио сохранено':state==='error'?(part.repair.error||'Ошибка; прежнее аудио сохранено'):state==='complete'?'Обновлён':'Готов';let previewing=fragmentPreview?.id===id&&fragmentPreview?.index===index;play.classList.toggle('is-active',previewing);play.disabled=!part.ready||previewing;stop.disabled=!previewing&&!['queued','generating'].includes(state);stop.title=previewing&&['queued','generating'].includes(state)?'Остановить воспроизведение и перегенерацию':previewing?'Остановить воспроизведение':'Остановить перегенерацию';stop.setAttribute('aria-label',stop.title);if(previewing)status.textContent=(state==='queued'||state==='generating'?'Воспроизведение · '+status.textContent:'Воспроизведение');regenerate.disabled=!part.ready||busy}updateMenu();play.onclick=async()=>{stopAudio();let context,preview;try{context=new (window.AudioContext||window.webkitAudioContext)();preview={source:null,context,abort:new AbortController(),id,index,onstop:updateMenu};fragmentPreview=preview;updateMenu();status.textContent='Загрузка фрагмента…';await context.resume();let r=await fetch('/api/speech-part?'+new URLSearchParams({id,index:String(index)}),{signal:preview.abort.signal});if(!r.ok)throw Error();let buffer=processSpeech(await context.decodeAudioData(await r.arrayBuffer()));if(fragmentPreview!==preview)return;let source=context.createBufferSource();preview.source=source;source.buffer=buffer;source.connect(context.destination);updateMenu();source.onended=()=>{if(fragmentPreview===preview){fragmentPreview=null;context.close().catch(()=>{});updateMenu()}};source.start()}catch(error){if(fragmentPreview===preview){fragmentPreview=null;if(context&&context.state!=='closed')context.close().catch(()=>{});updateMenu();if(error.name!=='AbortError')status.textContent='Не удалось воспроизвести фрагмент.'}}};async function pollRepair(){if(lifecycle.signal.aborted||!fragmentMode||fragmentJob!==id)return;try{let r=await fetch('/api/speech-parts?'+new URLSearchParams({id}));if(!r.ok)return;let updated=(await r.json()).find(p=>p.index===index);if(!updated)return;part.repair=updated.repair;let state=part.repair?.state;if(fragmentMenu===menu)updateMenu();if(['queued','generating','stopping'].includes(state))setTimeout(pollRepair,2000);else fragmentStatus.textContent=state==='complete'?'Фрагмент '+(index+1)+' обновлён.':state==='cancelled'?'Перегенерация остановлена; прежнее аудио сохранено.':part.repair?.error||'Не удалось перегенерировать фрагмент.'}catch{}}regenerate.onclick=async()=>{
  const pronunciation = prompt('Текст для озвучки этого фрагмента. Поставьте знак ударения после нужной гласной, например за́мок или замо́к. Текст страницы сохранится.', part.repair?.pronunciation ?? part.text);
  if (pronunciation === null) return;
  if (!pronunciation.trim() || pronunciation.length > 2000) {
    status.textContent = 'Введите текст длиной до 2000 символов.';
    return;
  }
  regenerate.disabled=true;status.textContent='Запуск…';try{let r=await fetch('/api/speech-regenerate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,index,pronunciation})});if(r.status===409)throw Error('Сначала остановите общую генерацию.');if(!r.ok)throw Error('Не удалось запустить перегенерацию.');part.repair={state:'queued'};updateMenu();fragmentStatus.textContent='Фрагмент '+(index+1)+' поставлен в очередь.';setTimeout(pollRepair,1000)}catch(error){status.textContent=error.message;regenerate.disabled=false}};stop.onclick=async()=>{let previewing=fragmentPreview?.id===id&&fragmentPreview?.index===index,repairing=['queued','generating'].includes(part.repair?.state);if(previewing)stopFragmentPreview();updateMenu();if(!repairing){status.textContent='Воспроизведение остановлено.';return}stop.disabled=true;try{let r=await fetch('/api/speech-regenerate-stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,index})});if(!r.ok)throw Error();let data=await r.json();part.repair={state:data.state};updateMenu();setTimeout(pollRepair,500)}catch{status.textContent='Не удалось остановить перегенерацию.';updateMenu()}};controls.append(play,stop,regenerate);menu.append(title,status,controls);document.body.append(menu);fragmentMenu=menu;let rect=mark.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight;menu.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8))+'px';menu.style.top=Math.max(8,Math.min(rect.bottom+5,window.innerHeight-height-8))+'px';(part.ready?play:regenerate).focus()}article.addEventListener('click',e=>{let mark=e.target.closest('.fragment-segment');if(mark&&fragmentMode){e.preventDefault();openFragmentMenu(mark)}});article.addEventListener('contextmenu',e=>{let mark=e.target.closest('.fragment-segment');if(mark&&fragmentMode){e.preventDefault();openFragmentMenu(mark)}});article.addEventListener('keydown',e=>{let mark=e.target.closest('.fragment-segment');if(mark&&fragmentMode&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openFragmentMenu(mark)}});document.addEventListener('pointerdown',e=>{if(fragmentMenu&&!fragmentMenu.contains(e.target)&&!e.target.closest('.fragment-segment'))closeFragmentMenu()},{signal:lifecycle.signal});document.addEventListener('keydown',e=>{if(e.key==='Escape')closeFragmentMenu()},{signal:lifecycle.signal});let previousFinal=null;async function refreshFinalVersion(){const key=progressKey;try{let r=await fetch('/api/speech-latest?'+new URLSearchParams({kind,path,...selectedVoiceSettings()}));if(!r.ok)return;let result=await r.json();if(lifecycle.signal.aborted||key!==progressKey)return;let job=result.job,status=document.querySelector('#final-version-status'),button=document.querySelector('#play-previous');let normal=s=>s.replace(/\s+/g,' ').trim();let stale=job&&normal(job.text)!==normal(article.innerText);previousFinal=stale?job:null;button.hidden=!stale;status.textContent=stale?'Итоговая озвучка создана для предыдущей версии текста. Она сохранится до готовности новой.':'';if(job&&!trackedJob)trackSpeechJob(job.id)}catch{}}let selectedPreview='';function rememberPreview(){let selected=window.getSelection();if(selected&&!selected.isCollapsed&&article.contains(selected.anchorNode)&&article.contains(selected.focusNode)){let value=selected.toString().trim();if(value)selectedPreview=value}}article.addEventListener('mouseup',rememberPreview);article.addEventListener('keyup',rememberPreview);document.querySelector('#preview-selection').onclick=async()=>{rememberPreview();let text=selectedPreview,voiceLabel=voiceChoice.selectedOptions[0]?.textContent||'выбранный голос',voiceValue=effectiveVoice(),previewSpeed=Number(speedControl.value);if(!text){speechStatus.textContent='Выделите текст для предпрослушивания.';return}if(text.length>1000){speechStatus.textContent='Выделите не более 1000 символов.';return}stopAudio();let run=generation,controller=new AbortController(),context;playbackAbort=controller;playerState='waiting';updateSpeechButtons();speechStatus.textContent='Подготовка: '+voiceLabel+'…';try{context=new (window.AudioContext||window.webkitAudioContext)();playbackContext=context;await context.resume();let r=await fetch('/api/speech-preview',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({kind,path,text,...selectedVoiceSettings(voiceValue, previewSpeed)})});if(!r.ok){const error=r.status===422?await r.json():null;throw Error(error?.error||'Не удалось подготовить предпрослушивание');}let buffer=processSpeech(await context.decodeAudioData(await r.arrayBuffer()));if(run!==generation)return;let source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);playbackSources=[source];playbackTotal=1;playbackIndex=0;let start=context.currentTime+.025;playbackSchedule=[{index:0,start,end:start+buffer.duration}];updatePlaybackProgress();playbackTimer=setInterval(()=>updatePlaybackProgress(),250);playerState='playing';updateSpeechButtons();speechStatus.textContent='Предпрослушивание · '+voiceLabel;source.onended=()=>{if(run!==generation)return;updatePlaybackProgress(true);if(playbackTimer)clearInterval(playbackTimer);playbackTimer=null;playbackSources=[];playbackContext=null;context.close().catch(()=>{});playerState='idle';updateSpeechButtons();speechStatus.textContent='Предпрослушивание завершено.'};source.start(start)}catch(error){if(run===generation){if(context&&context.state!=='closed')context.close().catch(()=>{});playbackContext=null;playerState='idle';updateSpeechButtons();speechStatus.textContent=error.message||'Ошибка предпрослушивания'}}};document.querySelector('#save-synthetic-voice').onclick=async()=>{if(!trackedJob){speechStatus.textContent='Сначала подготовьте первый фрагмент этой страницы.';return}let name=prompt('Название синтетического голоса');if(name===null)return;name=name.trim();if(!name||name.length>80){speechStatus.textContent='Введите название длиной до 80 символов.';return}try{let r=await fetch('/api/synthetic-voice-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:trackedJob,name,kind,path})});if(!r.ok)throw Error();let saved=await r.json(),selected='clone:'+saved.id;await refreshVoices(selected);localStorage.setItem('selectedVoice',selected);updateRenameButton();restoreVoiceJob();speechStatus.textContent='Эталон сохранён и выбран: '+saved.name+'. Его можно использовать на других страницах.'}catch{speechStatus.textContent='Не удалось сохранить эталон. Подготовьте первый фрагмент синтетического голоса на этой странице.'}};function restoreVoiceJob() {
  if (lifecycle.signal.aborted) return;
  const nextKey = 'speechJob:' + JSON.stringify([kind, path, selectedVoiceSettings()]);
  if (progressKey === nextKey) return;
  stopAudio();
  stopTracking();
  progressKey = nextKey;
  jobState = 'idle';
  previousFinal = null;
  document.querySelector('#play-previous').hidden = true;
  document.querySelector('#final-version-status').textContent = '';
  progressBox.hidden = true;
  updateSpeechButtons();
  const previousJob = localStorage.getItem(progressKey);
  if (previousJob) trackSpeechJob(previousJob);
  refreshFinalVersion();
}
async function startSpeechJob(existingOnly=false){const key=progressKey;let text=article.innerText.trim();if(!text)throw Error('Нет текста для чтения');let response=await fetch('/api/speech-job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,path,text,source_hash:data.source_hash,...selectedVoiceSettings(),headings:[...article.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(heading=>heading.innerText.trim()).filter(Boolean),speed:Number(speedControl.value),sentences:Number(document.querySelector('#sentence-count').value),existing_only:existingOnly})});if(!response.ok)throw Error(response.status===409?'Файл изменился. Обновите страницу перед генерацией.':existingOnly&&response.status===404?'Сначала подготовьте аудио':'Не удалось запустить генерацию');let job=await response.json();if(lifecycle.signal.aborted||key!==progressKey){if(key)localStorage.setItem(key,job.id);return job}trackSpeechJob(job.id);return job}async function speechJobStatus(id, allowError=false){let r=await fetch('/api/speech-job?'+new URLSearchParams({id}));if(!r.ok)throw Error('Задание недоступно');let state=await r.json();if(state.state==='error'&&!allowError)throw Error(state.error);if(state.state==='cancelled')throw Error('Генерация отменена');if(state.state==='superseded')throw Error('Эта версия озвучки заменена новой.');return state}document.querySelector('#prepare-speech').onclick=async()=>{stopAudio();let run=generation;jobState='starting';updateSpeechButtons();speechStatus.textContent='Запуск фоновой генерации…';try{let job=await startSpeechJob();while(run===generation){let state=await speechJobStatus(job.id);if(run!==generation)return;speechStatus.textContent='Подготовлено '+state.ready+' из '+state.total;if(state.state==='complete'){speechStatus.textContent='Все фрагменты готовы. Нажмите «Слушать».';return}if(state.state==='paused'){speechStatus.textContent='Генерация остановлена. Готовые фрагменты сохранены.';return}await new Promise(resolve=>setTimeout(resolve,1200))}}catch(e){if(run===generation){jobState='error';updateSpeechButtons();speechStatus.textContent=e.message||'Ошибка генерации'}}};async function playFinal(previous = false, seek = null) {
  stopAudio();
  const run = generation;
  const controller = new AbortController();
  playbackAbort = controller;
  const target = seek ? findSpeechPosition(seek.session.timeline, seek.time) : {index: 0, offset: 0};
  if (seek) {
    seekSession = seek.session;
    seekSession.position = seekSession.timeline[target.index].start + target.offset;
    updatePlaybackClock(false);
  }
  let ctx;
  try {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    playbackContext = ctx;
    await ctx.resume();
    if (run !== generation) return;
    playerState = 'waiting';
    updateSpeechButtons();
    speechStatus.textContent = 'Поиск подготовленного аудио…';
    let job = seek?.session.job;
    if (!job && previous) {
      if (!previousFinal) throw Error('Предыдущая версия не найдена');
      job = previousFinal;
      if (trackedJob !== job.id && !['starting', 'queued', 'generating', 'pausing'].includes(jobState)) {
        trackSpeechJob(job.id);
      }
    }
    if (!job) job = await startSpeechJob(true);
    if (run !== generation) return;

    const session = seek?.session ?? {
      job, durations: [], timeline: [], mode: playbackMode.value, gap: Number(speechGap.value) || 0,
    };
    seekSession = session;
    session.position = (session.timeline[target.index]?.start ?? 0) + target.offset;
    playbackTotal = job.total;
    playbackIndex = target.index;
    updatePlaybackProgress();
    playbackTimer = setInterval(updatePlaybackProgress, 250);

    const buffers = new Map();
    let lastReady = 0, timelineReady = 0, loadingTimeline = false;

    function recordDurations() {
      session.timeline = speechTimeline(session.durations, session.gap, job.heading_pauses);
      updatePlaybackClock(false);
    }

    async function loadBuffer(index) {
      const response = await fetch('/api/speech-part?' + new URLSearchParams({id: job.id, index: String(index)}),
                                   {signal: controller.signal});
      if (!response.ok) throw Error('Аудиофрагмент недоступен');
      return ctx.decodeAudioData(await response.arrayBuffer());
    }

    async function loadTimeline(ready) {
      if (loadingTimeline || ready <= timelineReady) return;
      loadingTimeline = true;
      try {
        const response = await fetch('/api/speech-timeline?' + new URLSearchParams({id: job.id}),
                                     {signal: controller.signal});
        if (!response.ok) return;
        const {durations} = await response.json();
        if (run !== generation) return;
        durations.forEach((duration, index) => {
          if (duration > 0) session.durations[index] = duration;
        });
        recordDurations();
        // Encodings without server-side duration metadata are measured by the existing decoder.
        for (let index = 0; index < durations.length && run === generation; index++) {
          if (session.durations[index] > 0) continue;
          session.durations[index] = (await loadBuffer(index)).duration;
          if (run !== generation) return;
          recordDurations();
        }
        timelineReady = durations.length;
      } catch {
        // The durations of chunks played normally also extend the timeline.
      } finally {
        loadingTimeline = false;
      }
    }

    async function waitBuffer(index) {
      while (run === generation) {
        const state = await speechJobStatus(job.id, true);
        if (run !== generation) break;
        lastReady = state.ready;
        void loadTimeline(lastReady);
        for (let n = index; n < Math.min(lastReady, index + 3, job.total); n++) {
          if (!buffers.has(n)) {
            buffers.set(n, loadBuffer(n).then(buffer => session.mode === 'legacy' ? normalizeSpeech(buffer) : buffer)
                        .catch(error => ({error})));
          }
        }
        if (buffers.has(index)) {
          const result = await buffers.get(index);
          if (result.error) throw result.error;
          return result;
        }
        if (state.state === 'error') throw Error(state.error);
        if (state.state === 'paused') throw Error('Готовые фрагменты закончились. Продолжите генерацию.');
        speechStatus.textContent = 'Подготовлено ' + state.ready + ' из ' + state.total + ' · ожидание части ' + (index + 1);
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      throw Error('Воспроизведение остановлено');
    }

    function schedule(buffer, index, after, offset = 0) {
      offset = Math.min(offset, Math.max(0, buffer.duration - 0.001));
      session.durations[index] = buffer.duration;
      recordDurations();
      const start = Math.max(ctx.currentTime + 0.025,
                             after === null ? 0 : after + speechGapBefore(index, session.gap, job.heading_pauses));
      const {source, end} = scheduleSpeechBuffer(ctx, buffer, start, offset, session.mode);
      const done = new Promise(resolve => {
        source.onended = () => {
          playbackSources = playbackSources.filter(item => item !== source);
          resolve();
        };
      });
      playbackSources.push(source);
      playbackSchedule.push({index, start, end, position: session.timeline[index].start + offset});
      return {end, done};
    }

    const first = await waitBuffer(target.index);
    if (run !== generation) return;
    buffers.delete(target.index);
    if (seek?.paused) {
      await ctx.suspend();
      if (run !== generation) return;
    }
    let current = schedule(first, target.index, null, target.offset);
    playerState = seek?.paused ? 'paused' : 'playing';
    updateSpeechButtons();
    speechStatus.textContent = 'Воспроизведение · подготовлено ' + lastReady + ' из ' + job.total;
    for (let i = target.index + 1; i < job.total; i++) {
      let next;
      try { next = await waitBuffer(i); }
      catch (error) { await current.done; throw error; }
      if (run !== generation) return;
      buffers.delete(i);
      const following = schedule(next, i, current.end);
      await current.done;
      if (run !== generation) return;
      current = following;
      speechStatus.textContent = 'Воспроизведение · подготовлено ' + lastReady + ' из ' + job.total;
    }
    await current.done;
    if (run !== generation) return;
    updatePlaybackProgress(true);
    clearInterval(playbackTimer);
    playbackTimer = null;
    controller.abort();
    await ctx.close();
    if (run !== generation) return;
    playbackContext = null;
    playbackSchedule = [];
    playerState = 'idle';
    updateSpeechButtons();
    speechStatus.textContent = 'Чтение завершено';
  } catch (error) {
    if (run !== generation) return;
    clearInterval(playbackTimer);
    playbackTimer = null;
    controller.abort();
    if (ctx && ctx.state !== 'closed') ctx.close().catch(() => {});
    playbackContext = null;
    playbackSchedule = [];
    playbackSources = [];
    playerState = 'idle';
    updateSpeechButtons();
    speechStatus.textContent = error.name === 'AbortError' ? 'Воспроизведение остановлено' : error.message || 'Ошибка воспроизведения';
  }
}
async function setPlaybackPaused(paused) {
  const context = playbackContext;
  if (!context || playerState !== (paused ? 'playing' : 'paused')) return;
  try {
    if (paused) await context.suspend();
    else await context.resume();
    if (context !== playbackContext) return;
    playerState = paused ? 'paused' : 'playing';
    updateSpeechButtons();
  } catch {
    speechStatus.textContent = 'Не удалось изменить воспроизведение';
  }
}
document.querySelector('#speak').onclick = () => {
  if (playerState === 'playing') return setPlaybackPaused(true);
  if (playerState === 'paused') return setPlaybackPaused(false);
  if (playerState === 'idle') return playFinal(false);
};
document.querySelector('#play-previous').onclick = () => playFinal(true);
document.querySelector('#pause-generation').onclick=async()=>{if(!trackedJob)return;let id=trackedJob;try{let r=await fetch('/api/speech-pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});if(!r.ok)throw Error();let result=await r.json();jobState=result.state;updateSpeechButtons();speechStatus.textContent=result.state==='pausing'?'Генерация остановится после текущего фрагмента.':'Генерация остановлена.';trackSpeechJob(id)}catch{speechStatus.textContent='Не удалось остановить генерацию.'}};document.querySelector('#stop').onclick = () => {
  const session = seekSession;
  stopAudio();
  if (session) {
    seekSession = session;
    session.position = 0;
    updatePlaybackClock(false);
  }
};
document.querySelector('#reset-speech').onclick=async()=>{stopAudio();stopTracking();jobState='idle';playbackTotal=0;document.querySelector('#playback-progress').hidden=true;updateSpeechButtons();localStorage.removeItem(progressKey);progressBox.hidden=true;speechStatus.textContent='Сброс сохранённой озвучки…';try{let r=await fetch('/api/speech-reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,path})});if(!r.ok)throw Error();speechStatus.textContent='Озвучка сброшена. Нажмите подготовку, чтобы создать её заново.';refreshFinalVersion()}catch{speechStatus.textContent='Не удалось сбросить озвучку'}};window.addEventListener('beforeunload',stopAudio,{signal:lifecycle.signal});
return () => { lifecycle.abort(); fragmentMode=false; fragmentVersion++; fragmentJob=null; stopTracking(); stopAudio(); closeFragmentMenu(); if(recordTimer) clearTimeout(recordTimer); if(recorder?.state==='recording') recorder.stop(); if(recordStream) recordStream.getTracks().forEach(t=>t.stop()); if(previewUrl) URL.revokeObjectURL(previewUrl); };
}
