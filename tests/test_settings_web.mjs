import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const names = ['books_root','games_root','voices_dir','qwen_tts_model','qwen_asr_model','piper_python','mlx_python','f5_python','f5_timeout','port','qwen_timeout','piper_timeout','asr_timeout','piper_sentence_silence','openai_model'];
const defaults = {books_root:'~/Documents/stories/books',games_root:'~/Development/games',voices_dir:'voices',qwen_tts_model:'models/qwen3-tts-0.6b',qwen_asr_model:'~/asr',piper_python:'.piper-env/bin/python',mlx_python:'.clone-env/bin/python',f5_python:'.f5-env/bin/python',f5_timeout:600,port:8765,qwen_timeout:150,piper_timeout:120,asr_timeout:300,piper_sentence_silence:.45,openai_model:'gpt-4o-mini-tts'};
const ids = [...names,'settings-form','save-settings','server-message','path-status','ui-status','openai-key-status','ui-voice','ui-custom-voices','ui-theme','ui-view','ui-group','ui-sidebar','ui-sentences','ui-speed'];
const elements = new Map(ids.map(id => [id, {value:'',textContent:'',hidden:false,disabled:false,options:[],handlers:{},classList:{toggle(){}},addEventListener(type,fn){this.handlers[type]=fn;}}]));
elements.get('settings-form').reportValidity = () => true;
for (const [id,values] of Object.entries({'ui-theme':['dark','light'],'ui-view':['cards','table'],'ui-group':['none','tags'],'ui-sidebar':['outline','notes','speech'],'ui-sentences':['1','2','3','4','5'],'ui-speed':['0.7','0.8','0.9','1','1.1','1.2','1.3'],'ui-voice':['local:ruslan','local:irina','local:dmitri','openai:marin']})) elements.get(id).options = values.map(value=>({value}));
elements.get('ui-custom-voices').replaceChildren=()=>{};
elements.get('ui-custom-voices').append=option=>elements.get('ui-voice').options.push(option);
const theme = new Map();
globalThis.document = {getElementById:id=>elements.get(id),querySelector:selector=>elements.get(selector.slice(1)),createElement:()=>({}),body:{classList:{toggle:(name,on)=>theme.set(name,on)}}};
const storage = new Map();
globalThis.localStorage = {getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)};
globalThis.location = {port:'8765',protocol:'http:'};
let savedPayload;
globalThis.fetch = async (url,options) => {
  if (url==='/api/voices') return {ok:true,json:async()=>[{id:'123',name:'Мой голос',emotion:'joy'}]};
  if (url==='/api/settings' && !options) return {ok:true,json:async()=>({values:defaults,revision:'missing',restart_required:false,generation_active:false,openai_key_configured:false,path_checks:{qwen_asr_model:false}})};
  if (url==='/api/settings' && options?.method==='POST') {
    savedPayload=JSON.parse(options.body);
    return {ok:true,json:async()=>({values:savedPayload.values,revision:'new',restart_required:true,generation_active:false,path_checks:{qwen_asr_model:true}})};
  }
  throw Error('Unexpected request');
};
const source=await readFile(new URL('../web/settings.js',import.meta.url),'utf8');
await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(elements.get('books_root').value,defaults.books_root);
assert.equal(elements.get('save-settings').disabled,false);
assert.match(elements.get('path-status').textContent,/Qwen ASR/);
assert.equal(elements.get('ui-voice').options.at(-1).value,'clone:123');
assert.equal(elements.get('ui-voice').options.at(-1).textContent,'Мой голос · радость');
elements.get('ui-theme').value='light';elements.get('ui-theme').handlers.change();
assert.equal(storage.get('projectTheme'),'light');assert.equal(theme.get('light'),true);
elements.get('port').value='9876';await elements.get('settings-form').handlers.submit({preventDefault(){}});
assert.equal(savedPayload.values.port,9876);assert.equal(savedPayload.revision,'missing');
assert.ok(!('OPENAI_API_KEY' in savedPayload.values));
assert.match(elements.get('server-message').textContent,/после перезапуска/);
assert.match(elements.get('server-message').textContent,/127\.0\.0\.1:9876/);
assert.equal(elements.get('path-status').hidden,true);
console.log('Settings UI checks passed');
