// Chat, review and speech UI. Credentials stay on the Python server.
let currentSummary=null, chatCapabilities={}, chatEpoch=0, pendingTurn=null;
let voiceState=null, voiceTimer=null, voiceBlob=null, voiceElapsed=0;
const micIcon='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';

async function api(path,data={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),path==='transcribe'?55000:45000);
 try{const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:controller.signal});const v=await r.json();if(!r.ok){const e=Error(v.error||'請求失敗，請重試。');e.retryable=v.retryable;throw e}return v}
 catch(e){if(e.name==='AbortError')throw Error('請求超時，請點擊重試。相同消息不會重複提交。');if(e instanceof TypeError)throw Error('無法連接服務，請檢查網絡或本地 Python 服務。');throw e}
 finally{clearTimeout(timer)}
}
function stopVoice(){
 clearInterval(voiceTimer);voiceTimer=null;
 const old=voiceState;voiceState=null;
 if(old){old.cancelled=true;try{old.recognition?.abort()}catch(e){}try{if(old.recorder?.state==='recording')old.recorder.stop()}catch(e){}old.stream?.getTracks().forEach(t=>t.stop())}
}
function leaveChat(){chatEpoch++;stopVoice();voiceBlob=null;sending=false}
window.addEventListener('pagehide',stopVoice);

async function startChat(){
 const selected=document.querySelector('input[name=appt]:checked');if(!selected)return error(Error('請先選擇一條覆診預約。'));
 const start=document.querySelector('#start');if(start.disabled)return;start.disabled=true;
 try{const v=await api('start',{username,appointment_id:selected.value});sid=v.service_id;pendingTurn=null;sessionStorage.setItem('active-chat',JSON.stringify({sid,username}));drawChat(v.summary,v.capabilities,[{role:'assistant',content:v.reply}])}
 catch(e){error(e);if(start.isConnected)start.disabled=false}
}
function drawChat(summary,capabilities,history){
 role='user';nav.hidden=false;currentSummary=summary;chatCapabilities=capabilities||{};
 shell(`<h1 class="chat-page-title">一起確認覆診安排</h1><div class="chat-layout enhanced-chat"><section class="card chat-panel"><div class="chat-title"><span class="assistant-avatar" aria-hidden="true">··</span><div><strong>CareVisit 協助助手</strong><small id="model-mode"></small></div></div><div class="chat" id="chat" role="log" aria-label="申請對話" aria-live="polite"></div><div class="compose-area"><div id="turn-error" role="alert" hidden></div><div id="voice-review" hidden><label for="voice-text">語音轉寫 · 核對後使用</label><textarea id="voice-text" rows="2" maxlength="1000"></textarea><div class="voice-review-actions"><button class="secondary" onclick="discardTranscript()">取消</button><button onclick="acceptTranscript()">使用這段文字</button></div></div><div class="voice-controls"><label for="voice-mode">語音方式</label><select id="voice-mode"><option value="upload" ${capabilities?.speech_configured?'':'disabled'}>錄音轉寫 API</option><option value="browser">瀏覽器識別</option></select><select id="voice-lang" aria-label="語音語言"><option value="zh-HK">粵語</option><option value="zh-CN">普通話</option><option value="en-US">English</option></select><span id="voice-status" role="status"></span></div><label class="input-label" for="message">您的回答</label><div class="composer"><button id="mic" class="mic-button" onclick="toggleVoice()" aria-label="開始語音輸入" title="開始語音輸入">${micIcon}</button><input id="message" type="text" maxlength="1000" placeholder="輸入文字，或點擊麥克風" autocomplete="off"><button id="send" onclick="sendMessage()">發送</button></div><p class="voice-note" id="voice-note"></p></div></section><aside class="chat-aside live-summary"><div class="summary-heading"><h2>您的覆診安排</h2></div><div id="summary-content"></div><div id="summary-actions"></div></aside></div>`);
 for(const m of history)bubble(m.content,m.role==='user');
 document.querySelector('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing)sendMessage()});
 document.querySelector('#voice-mode').value=capabilities?.speech_configured?'upload':'browser';
 document.querySelector('#voice-mode').onchange=updateVoiceNote;updateVoiceNote();renderSummary(summary);updateModelMode(capabilities);
 if(pendingTurn)showTurnError('上一條消息尚未確認結果，請重試以同步狀態。');
 document.querySelector('#message')?.focus();
}
function updateModelMode(c){chatCapabilities=c||{};const el=document.querySelector('#model-mode');if(el)el.textContent=c?.chat_configured?'大模型需求理解':'離線演示 · 關鍵詞理解'}
function updateVoiceNote(){const mode=document.querySelector('#voice-mode');if(!mode)return;document.querySelector('#voice-lang').hidden=mode.value==='upload';document.querySelector('#voice-note').textContent=mode.value==='upload'?'錄音最長 60 秒，停止後發送至配置的轉寫服務；文字核對後再發送。':'瀏覽器識別可能使用在線語音服務；請允許麥克風權限，識別後先核對文字。'}
function renderSummary(s){
 currentSummary=s;const target=document.querySelector('#summary-content');if(!target)return;
 const item=(k,label)=>{const v=s[k];const missing=v===null||v===undefined||v==='';const boolean=typeof v==='boolean';const display=missing?'待補充':boolean?(v?'需要':'不需要'):String(v).replace('T',' ');const type=missing?'summary-missing':boolean?(v?'summary-needed':'summary-none'):'';return `<div><dt>${label}</dt><dd><span class="${type}">${esc(display)}</span></dd></div>`};
 target.innerHTML=`<section class="summary-appointment"><h3>${esc(s.hospital||'待補充醫院')}</h3><p>${esc(String(s.arrival||'待補充時間').replace('T',' '))}</p></section><section class="summary-section"><dl>${item('escort','陪診')}${item('outbound','去程接送')}${item('return_trip','回程接送')}${item('wheelchair','輪椅協助')}</dl></section><section class="summary-section summary-location"><dl>${item('district','地區')}${item('address','地址')}</dl></section><p class="summary-status" role="status" ${['pending','cancelled'].includes(s.status)?'':'hidden'}><span aria-hidden="true"></span>${s.status==='pending'?'已提交，等待社區處理':s.status==='cancelled'?'已取消申請':s.stage==='final_confirm'?'':''}</p>`;
 document.querySelector('#summary-actions').innerHTML=s.stage==='final_confirm'?'<button id="confirm-submit" onclick="sendMessage(\'確認提交\')">確認提交</button><div class="summary-edit"><button class="secondary" onclick="sendMessage(\'修改需求\')">修改需求</button><button class="secondary" onclick="sendMessage(\'修改地址\')">修改地址</button></div>':'';
 const finished=['complete','cancelled'].includes(s.stage);
 if(finished){stopVoice();sessionStorage.removeItem('active-chat');document.querySelector('.composer').classList.add('composer-complete');document.querySelector('.composer').innerHTML='<span class="completion-label"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>'+ (s.stage==='cancelled'?'申請已取消':'申請已提交')+'</span><button id="return-home" onclick="userHome(\'申請狀態已更新，可在服務進度中查看。\')">返回我的覆診</button>';document.querySelector('.voice-controls').hidden=true;document.querySelector('#voice-note').hidden=true;document.querySelector('#voice-review').hidden=true}
}
function setChatBusy(busy){
 for(const selector of ['#message','#send','#mic','#voice-mode','#voice-lang','#summary-actions button'])document.querySelectorAll(selector).forEach(x=>x.disabled=busy);
 const b=document.querySelector('#send');if(b)b.textContent=busy?'處理中…':'發送';
}
function showTurnError(message){const box=document.querySelector('#turn-error');if(!box)return;box.hidden=false;box.replaceChildren();const span=document.createElement('span');span.textContent=message;const retry=document.createElement('button');retry.textContent='重試這條消息';retry.className='secondary';retry.onclick=()=>sendMessage();box.append(span,retry)}
async function sendMessage(explicit){
 const input=document.querySelector('#message');if(!input||sending||voiceState)return;
 const text=pendingTurn?.text||(typeof explicit==='string'?explicit:input.value.trim());if(!text)return;
 if(!pendingTurn){pendingTurn={text,id:crypto.randomUUID()};bubble(text,true);input.value=''}
 const turn=pendingTurn,epoch=chatEpoch,requestSid=sid;sessionStorage.setItem('pending-turn',JSON.stringify({sid:requestSid,...turn}));sending=true;setChatBusy(true);document.querySelector('#turn-error').hidden=true;
 try{const v=await api('message',{service_id:requestSid,username,message:turn.text,request_id:turn.id});if(epoch!==chatEpoch)return;pendingTurn=null;sessionStorage.removeItem('pending-turn');bubble(v.reply);updateModelMode(v.capabilities);renderSummary(v.summary)}
 catch(e){if(epoch===chatEpoch)showTurnError(e.message)}
 finally{if(epoch===chatEpoch){sending=false;setChatBusy(false);if(pendingTurn){document.querySelector('#message').disabled=true;document.querySelector('#send').disabled=true;document.querySelector('#mic').disabled=true;document.querySelectorAll('#summary-actions button').forEach(x=>x.disabled=true)}}}
}
async function resumeChat(){
 const saved=JSON.parse(sessionStorage.getItem('active-chat')||'null');if(!saved)return landing();username=saved.username;sid=saved.sid;
 try{const v=await api('session',{username,service_id:sid});const pending=JSON.parse(sessionStorage.getItem('pending-turn')||'null');pendingTurn=pending?.sid===sid?pending:null;if(['complete','cancelled'].includes(v.summary.stage)){pendingTurn=null;sessionStorage.removeItem('pending-turn')}drawChat(v.summary,v.capabilities,v.messages)}catch(e){landing();error(e)}
}

function voiceStatus(text){const e=document.querySelector('#voice-status');if(e)e.textContent=text}
function recordingUI(active){const b=document.querySelector('#mic');if(b){b.innerHTML=active?'停止':micIcon;b.setAttribute('aria-label',active?'停止錄音':'開始語音輸入');b.classList.toggle('recording',active)}for(const id of ['send','message','voice-mode','voice-lang']){const e=document.getElementById(id);if(e)e.disabled=active}document.querySelectorAll('#summary-actions button').forEach(x=>x.disabled=active)}
function startVoiceTimer(){voiceElapsed=0;voiceStatus('正在錄音 00:00');voiceTimer=setInterval(()=>{voiceElapsed++;voiceStatus('正在錄音 00:'+String(voiceElapsed).padStart(2,'0'));if(voiceElapsed>=60)finishVoice()},1000)}
function finishVoice(){clearInterval(voiceTimer);if(!voiceState)return;try{if(voiceState.recorder?.state==='recording')voiceState.recorder.stop();else voiceState.recognition?.stop()}catch(e){stopVoice();recordingUI(false)}}
function showTranscript(text){const review=document.querySelector('#voice-review');if(!review)return;review.hidden=false;document.querySelector('#voice-text').value=text;voiceStatus('轉寫完成，請核對');document.querySelector('#voice-text').focus()}
function acceptTranscript(){const text=document.querySelector('#voice-text').value.trim();if(!text)return;const input=document.querySelector('#message');const value=[input.value.trim(),text].filter(Boolean).join('，');if(value.length>1000){voiceStatus('文字超過 1000 字，請先縮短轉寫內容。');return}input.value=value;discardTranscript();input.focus()}
function discardTranscript(){document.querySelector('#voice-review').hidden=true;document.querySelector('#voice-text').value='';voiceBlob=null;voiceStatus('')}
async function toggleVoice(){
 if(sending||pendingTurn)return;if(voiceState){finishVoice();return}
 const mode=document.querySelector('#voice-mode').value;stopVoice();const epoch=chatEpoch;const state={cancelled:false};voiceState=state;recordingUI(true);
 if(mode==='browser'){
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){voiceState=null;recordingUI(false);voiceStatus('此瀏覽器不支持語音識別，請配置錄音轉寫 API 或使用文字。');return}
  const recognition=new Recognition();state.recognition=recognition;recognition.lang=document.querySelector('#voice-lang').value;recognition.continuous=true;recognition.interimResults=true;let transcript='',failure='';
  recognition.onresult=e=>{transcript=Array.from(e.results).map(r=>r[0].transcript).join('');voiceStatus('識別中：'+transcript.slice(-45))};
  recognition.onerror=e=>{failure=({'not-allowed':'麥克風權限未開啟，請在瀏覽器設置中允許。','no-speech':'沒有聽到清晰語音，請重試。','audio-capture':'找不到可用的麥克風。','network':'瀏覽器語音服務連接失敗，可切換錄音轉寫 API。','service-not-allowed':'瀏覽器語音服務不可用，可切換錄音轉寫 API。'})[e.error]||'語音識別未完成，請重試。'};
  recognition.onend=()=>{if(state.cancelled||epoch!==chatEpoch)return;clearInterval(voiceTimer);voiceState=null;recordingUI(false);if(transcript.trim())showTranscript(transcript.slice(0,1000));else voiceStatus(failure||'沒有識別到語音，請重試。')};
  try{recognition.start();startVoiceTimer()}catch(e){voiceState=null;recordingUI(false);voiceStatus('無法啟動麥克風，請檢查權限。')}return;
 }
 try{
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('此瀏覽器不支持錄音，請使用新版 Edge 或 Chrome。');
  voiceStatus('等待麥克風權限…');const stream=await navigator.mediaDevices.getUserMedia({audio:true});state.stream=stream;
  if(state.cancelled||epoch!==chatEpoch){stream.getTracks().forEach(t=>t.stop());return}
  const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw Error('瀏覽器錄音格式不受支持。');
  const recorder=new MediaRecorder(stream,{mimeType:mime});state.recorder=recorder;const chunks=[];let bytes=0;
  recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>6_000_000)finishVoice()}};
  recorder.onerror=()=>{stopVoice();recordingUI(false);voiceStatus('錄音失敗，請重試。')};
  recorder.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());clearInterval(voiceTimer);if(state.cancelled||epoch!==chatEpoch)return;voiceState=null;recordingUI(false);setChatBusy(true);voiceStatus('正在整理錄音…');try{const wav=await audioToWav(new Blob(chunks,{type:mime}));if(epoch!==chatEpoch)return;voiceBlob=wav;await uploadVoice(epoch)}catch(e){if(epoch===chatEpoch){setChatBusy(false);voiceStatus('無法讀取錄音，請重新錄製或使用瀏覽器識別。')}}};
  recorder.start(1000);startVoiceTimer();
 }catch(e){if(epoch!==chatEpoch)return;stopVoice();recordingUI(false);voiceStatus(e.name==='NotAllowedError'?'麥克風權限未開啟，請允許後重試。':e.name==='NotFoundError'?'找不到可用的麥克風。':e.message)}
}
async function audioToWav(blob){
 const decoder=new OfflineAudioContext(1,1,16000);const decoded=await decoder.decodeAudioData(await blob.arrayBuffer());
 if(decoded.duration>62)throw Error('錄音過長');
 const context=new OfflineAudioContext(1,Math.ceil(decoded.duration*16000),16000);const source=context.createBufferSource();source.buffer=decoded;source.connect(context.destination);source.start();
 const rendered=await context.startRendering(),samples=rendered.getChannelData(0),buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
 const word=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i))};
 word(0,'RIFF');view.setUint32(4,36+samples.length*2,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,samples.length*2,true);
 for(let i=0;i<samples.length;i++){const sample=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true)}
 return new Blob([buffer],{type:'audio/wav'});
}
async function uploadVoice(epoch=chatEpoch){
 if(!voiceBlob)return;voiceStatus('正在轉寫…');setChatBusy(true);const source=voiceBlob;
 try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(source)});const v=await api('transcribe',{audio:data,mime:source.type});if(epoch===chatEpoch)showTranscript(v.text)}
 catch(e){if(epoch===chatEpoch){voiceStatus(e.message);const status=document.querySelector('#voice-status');const retry=document.createElement('button');retry.className='secondary';retry.textContent='重試轉寫';retry.onclick=()=>uploadVoice();status.append(retry)}}
 finally{if(epoch===chatEpoch)setChatBusy(false)}
}
