// Chat, review and speech UI. Credentials stay on the Python server.
let currentSummary=null, chatCapabilities={}, chatEpoch=0, pendingTurn=null;
let voiceState=null, voiceTimer=null, voiceBlob=null, voiceElapsed=0;
const micIcon='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';

async function api(path,data={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),path==='transcribe'?55000:45000);
 try{const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:controller.signal});const v=await r.json();if(!r.ok){const e=Error(v.error||'请求失败，请重试。');e.retryable=v.retryable;throw e}return v}
 catch(e){if(e.name==='AbortError')throw Error('请求超时，请点击重试。相同消息不会重复提交。');if(e instanceof TypeError)throw Error('无法连接服务，请检查网络或本地 Python 服务。');throw e}
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
 const selected=document.querySelector('input[name=appt]:checked');if(!selected)return error(Error('请先选择一条覆诊预约。'));
 const start=document.querySelector('#start');if(start.disabled)return;start.disabled=true;
 try{const v=await api('start',{username,appointment_id:selected.value});sid=v.service_id;pendingTurn=null;sessionStorage.setItem('active-chat',JSON.stringify({sid,username}));drawChat(v.summary,v.capabilities,[{role:'assistant',content:v.reply}])}
 catch(e){error(e);if(start.isConnected)start.disabled=false}
}
function drawChat(summary,capabilities,history){
 role='user';nav.hidden=false;currentSummary=summary;chatCapabilities=capabilities||{};
 shell(`<h1 class="chat-page-title">一起确认覆诊安排</h1><div class="chat-layout enhanced-chat"><section class="card chat-panel"><div class="chat-title"><span class="assistant-avatar" aria-hidden="true">··</span><div><strong>CareVisit 协助助手</strong><small id="model-mode"></small></div></div><div class="chat" id="chat" role="log" aria-label="申请对话" aria-live="polite"></div><div class="compose-area"><div id="turn-error" role="alert" hidden></div><div id="voice-review" hidden><label for="voice-text">语音转写 · 核对后使用</label><textarea id="voice-text" rows="2" maxlength="1000"></textarea><div class="voice-review-actions"><button class="secondary" onclick="discardTranscript()">取消</button><button onclick="acceptTranscript()">使用这段文字</button></div></div><div class="voice-controls"><label for="voice-mode">语音方式</label><select id="voice-mode"><option value="upload" ${capabilities?.speech_configured?'':'disabled'}>录音转写 API</option><option value="browser">浏览器识别</option></select><select id="voice-lang" aria-label="语音语言"><option value="zh-CN">普通话</option><option value="zh-HK">粤语</option><option value="en-US">English</option></select><span id="voice-status" role="status"></span></div><label class="input-label" for="message">您的回答</label><div class="composer"><button id="mic" class="mic-button" onclick="toggleVoice()" aria-label="开始语音输入" title="开始语音输入">${micIcon}</button><input id="message" type="text" maxlength="1000" placeholder="输入文字，或点击麦克风" autocomplete="off"><button id="send" onclick="sendMessage()">发送</button></div><p class="voice-note" id="voice-note"></p></div></section><aside class="chat-aside live-summary"><div class="summary-heading"><h2>您的覆诊安排</h2></div><div id="summary-content"></div><div id="summary-actions"></div></aside></div>`);
 for(const m of history)bubble(m.content,m.role==='user');
 document.querySelector('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing)sendMessage()});
 document.querySelector('#voice-mode').value=capabilities?.speech_configured?'upload':'browser';
 document.querySelector('#voice-mode').onchange=updateVoiceNote;updateVoiceNote();renderSummary(summary);updateModelMode(capabilities);
 if(pendingTurn)showTurnError('上一条消息尚未确认结果，请重试以同步状态。');
 document.querySelector('#message')?.focus();
}
function updateModelMode(c){chatCapabilities=c||{};const el=document.querySelector('#model-mode');if(el)el.textContent=c?.chat_configured?'大模型需求理解':'离线演示 · 关键词理解'}
function updateVoiceNote(){const mode=document.querySelector('#voice-mode');if(!mode)return;document.querySelector('#voice-lang').hidden=mode.value==='upload';document.querySelector('#voice-note').textContent=mode.value==='upload'?'录音最长 60 秒，停止后发送至配置的转写服务；文字核对后再发送。':'浏览器识别可能使用在线语音服务；请允许麦克风权限，识别后先核对文字。'}
function renderSummary(s){
 currentSummary=s;const target=document.querySelector('#summary-content');if(!target)return;
 const item=(k,label)=>{const v=s[k];const missing=v===null||v===undefined||v==='';const boolean=typeof v==='boolean';const display=missing?'待补充':boolean?(v?'需要':'不需要'):String(v).replace('T',' ');const type=missing?'summary-missing':boolean?(v?'summary-needed':'summary-none'):'';return `<div><dt>${label}</dt><dd><span class="${type}">${esc(display)}</span></dd></div>`};
 target.innerHTML=`<section class="summary-appointment"><h3>${esc(s.hospital||'待补充医院')}</h3><p>${esc(String(s.arrival||'待补充时间').replace('T',' '))}</p></section><section class="summary-section"><dl>${item('escort','陪诊')}${item('outbound','去程接送')}${item('return_trip','回程接送')}${item('wheelchair','轮椅协助')}</dl></section><section class="summary-section summary-location"><dl>${item('district','地区')}${item('address','地址')}</dl></section><p class="summary-status" role="status" ${['pending','cancelled'].includes(s.status)?'':'hidden'}><span aria-hidden="true"></span>${s.status==='pending'?'已提交，等待社区处理':s.status==='cancelled'?'已取消申请':s.stage==='final_confirm'?'':''}</p>`;
 document.querySelector('#summary-actions').innerHTML=s.stage==='final_confirm'?'<button id="confirm-submit" onclick="sendMessage(\'确认提交\')">确认提交</button><div class="summary-edit"><button class="secondary" onclick="sendMessage(\'修改需求\')">修改需求</button><button class="secondary" onclick="sendMessage(\'修改地址\')">修改地址</button></div>':'';
 const finished=['complete','cancelled'].includes(s.stage);
 if(finished){stopVoice();sessionStorage.removeItem('active-chat');document.querySelector('.composer').classList.add('composer-complete');document.querySelector('.composer').innerHTML='<span class="completion-label"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>'+ (s.stage==='cancelled'?'申请已取消':'申请已提交')+'</span><button id="return-home" onclick="userHome(\'申请状态已更新，可在服务进度中查看。\')">返回我的覆诊</button>';document.querySelector('.voice-controls').hidden=true;document.querySelector('#voice-note').hidden=true;document.querySelector('#voice-review').hidden=true}
}
function setChatBusy(busy){
 for(const selector of ['#message','#send','#mic','#voice-mode','#voice-lang','#summary-actions button'])document.querySelectorAll(selector).forEach(x=>x.disabled=busy);
 const b=document.querySelector('#send');if(b)b.textContent=busy?'处理中…':'发送';
}
function showTurnError(message){const box=document.querySelector('#turn-error');if(!box)return;box.hidden=false;box.replaceChildren();const span=document.createElement('span');span.textContent=message;const retry=document.createElement('button');retry.textContent='重试这条消息';retry.className='secondary';retry.onclick=()=>sendMessage();box.append(span,retry)}
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
function recordingUI(active){const b=document.querySelector('#mic');if(b){b.innerHTML=active?'停止':micIcon;b.setAttribute('aria-label',active?'停止录音':'开始语音输入');b.classList.toggle('recording',active)}for(const id of ['send','message','voice-mode','voice-lang']){const e=document.getElementById(id);if(e)e.disabled=active}document.querySelectorAll('#summary-actions button').forEach(x=>x.disabled=active)}
function startVoiceTimer(){voiceElapsed=0;voiceStatus('正在录音 00:00');voiceTimer=setInterval(()=>{voiceElapsed++;voiceStatus('正在录音 00:'+String(voiceElapsed).padStart(2,'0'));if(voiceElapsed>=60)finishVoice()},1000)}
function finishVoice(){clearInterval(voiceTimer);if(!voiceState)return;try{if(voiceState.recorder?.state==='recording')voiceState.recorder.stop();else voiceState.recognition?.stop()}catch(e){stopVoice();recordingUI(false)}}
function showTranscript(text){const review=document.querySelector('#voice-review');if(!review)return;review.hidden=false;document.querySelector('#voice-text').value=text;voiceStatus('转写完成，请核对');document.querySelector('#voice-text').focus()}
function acceptTranscript(){const text=document.querySelector('#voice-text').value.trim();if(!text)return;const input=document.querySelector('#message');const value=[input.value.trim(),text].filter(Boolean).join('，');if(value.length>1000){voiceStatus('文字超过 1000 字，请先缩短转写内容。');return}input.value=value;discardTranscript();input.focus()}
function discardTranscript(){document.querySelector('#voice-review').hidden=true;document.querySelector('#voice-text').value='';voiceBlob=null;voiceStatus('')}
async function toggleVoice(){
 if(sending||pendingTurn)return;if(voiceState){finishVoice();return}
 const mode=document.querySelector('#voice-mode').value;stopVoice();const epoch=chatEpoch;const state={cancelled:false};voiceState=state;recordingUI(true);
 if(mode==='browser'){
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){voiceState=null;recordingUI(false);voiceStatus('此浏览器不支持语音识别，请配置录音转写 API 或使用文字。');return}
  const recognition=new Recognition();state.recognition=recognition;recognition.lang=document.querySelector('#voice-lang').value;recognition.continuous=true;recognition.interimResults=true;let transcript='',failure='';
  recognition.onresult=e=>{transcript=Array.from(e.results).map(r=>r[0].transcript).join('');voiceStatus('识别中：'+transcript.slice(-45))};
  recognition.onerror=e=>{failure=({'not-allowed':'麦克风权限未开启，请在浏览器设置中允许。','no-speech':'没有听到清晰语音，请重试。','audio-capture':'找不到可用的麦克风。','network':'浏览器语音服务连接失败，可切换录音转写 API。','service-not-allowed':'浏览器语音服务不可用，可切换录音转写 API。'})[e.error]||'语音识别未完成，请重试。'};
  recognition.onend=()=>{if(state.cancelled||epoch!==chatEpoch)return;clearInterval(voiceTimer);voiceState=null;recordingUI(false);if(transcript.trim())showTranscript(transcript.slice(0,1000));else voiceStatus(failure||'没有识别到语音，请重试。')};
  try{recognition.start();startVoiceTimer()}catch(e){voiceState=null;recordingUI(false);voiceStatus('无法启动麦克风，请检查权限。')}return;
 }
 try{
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('此浏览器不支持录音，请使用新版 Edge 或 Chrome。');
  voiceStatus('等待麦克风权限…');const stream=await navigator.mediaDevices.getUserMedia({audio:true});state.stream=stream;
  if(state.cancelled||epoch!==chatEpoch){stream.getTracks().forEach(t=>t.stop());return}
  const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw Error('浏览器录音格式不受支持。');
  const recorder=new MediaRecorder(stream,{mimeType:mime});state.recorder=recorder;const chunks=[];let bytes=0;
  recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>6_000_000)finishVoice()}};
  recorder.onerror=()=>{stopVoice();recordingUI(false);voiceStatus('录音失败，请重试。')};
  recorder.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());clearInterval(voiceTimer);if(state.cancelled||epoch!==chatEpoch)return;voiceState=null;recordingUI(false);setChatBusy(true);voiceStatus('正在整理录音…');try{const wav=await audioToWav(new Blob(chunks,{type:mime}));if(epoch!==chatEpoch)return;voiceBlob=wav;await uploadVoice(epoch)}catch(e){if(epoch===chatEpoch){setChatBusy(false);voiceStatus('无法读取录音，请重新录制或使用浏览器识别。')}}};
  recorder.start(1000);startVoiceTimer();
 }catch(e){if(epoch!==chatEpoch)return;stopVoice();recordingUI(false);voiceStatus(e.name==='NotAllowedError'?'麦克风权限未开启，请允许后重试。':e.name==='NotFoundError'?'找不到可用的麦克风。':e.message)}
}
async function audioToWav(blob){
 const decoder=new OfflineAudioContext(1,1,16000);const decoded=await decoder.decodeAudioData(await blob.arrayBuffer());
 if(decoded.duration>62)throw Error('录音过长');
 const context=new OfflineAudioContext(1,Math.ceil(decoded.duration*16000),16000);const source=context.createBufferSource();source.buffer=decoded;source.connect(context.destination);source.start();
 const rendered=await context.startRendering(),samples=rendered.getChannelData(0),buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
 const word=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i))};
 word(0,'RIFF');view.setUint32(4,36+samples.length*2,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,samples.length*2,true);
 for(let i=0;i<samples.length;i++){const sample=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true)}
 return new Blob([buffer],{type:'audio/wav'});
}
async function uploadVoice(epoch=chatEpoch){
 if(!voiceBlob)return;voiceStatus('正在转写…');setChatBusy(true);const source=voiceBlob;
 try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(source)});const v=await api('transcribe',{audio:data,mime:source.type});if(epoch===chatEpoch)showTranscript(v.text)}
 catch(e){if(epoch===chatEpoch){voiceStatus(e.message);const status=document.querySelector('#voice-status');const retry=document.createElement('button');retry.className='secondary';retry.textContent='重试转写';retry.onclick=()=>uploadVoice();status.append(retry)}}
 finally{if(epoch===chatEpoch)setChatBusy(false)}
}
