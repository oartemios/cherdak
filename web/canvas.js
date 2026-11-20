import { markdown } from './markdown.js';

export function renderCanvas(text) {
  const data = JSON.parse(text);
  if (!Array.isArray(data.nodes) || (data.edges != null && !Array.isArray(data.edges))) throw Error('Некорректный холст');
  const nodes = data.nodes.filter(n => n && typeof n.id === 'string' && [n.x,n.y,n.width,n.height].every(Number.isFinite) && n.width > 0 && n.height > 0);
  const container = document.createElement('div'); container.className = 'canvas-view';
  if (!nodes.length) { container.textContent = 'На холсте нет карточек.'; return container; }
  const left=Math.min(...nodes.map(n=>n.x))-50, top=Math.min(...nodes.map(n=>n.y))-50;
  const width=Math.max(...nodes.map(n=>n.x+n.width))-left+50, height=Math.max(...nodes.map(n=>n.y+n.height))-top+50;
  const stage=document.createElement('div'); stage.className='canvas-stage'; stage.style.width=width+'px'; stage.style.height=height+'px';
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('width',width);svg.setAttribute('height',height);svg.classList.add('canvas-edges');
  const point=(n,side)=>({x:n.x-left+(side==='left'?0:side==='right'?n.width:n.width/2),y:n.y-top+(side==='top'?0:side==='bottom'?n.height:n.height/2)});
  const byId=new Map(nodes.map(n=>[n.id,n]));
  for(const edge of data.edges||[]) {const a=byId.get(edge.fromNode),b=byId.get(edge.toNode);if(!a||!b)continue;const from=point(a,edge.fromSide),to=point(b,edge.toSide);const line=document.createElementNS(svg.namespaceURI,'line');for(const [key,value] of Object.entries({x1:from.x,y1:from.y,x2:to.x,y2:to.y}))line.setAttribute(key,value);svg.append(line);if(edge.toEnd!=='none'){const angle=Math.atan2(to.y-from.y,to.x-from.x), size=9;const arrow=document.createElementNS(svg.namespaceURI,'polygon');arrow.setAttribute('points',`${to.x},${to.y} ${to.x-size*Math.cos(angle-.45)},${to.y-size*Math.sin(angle-.45)} ${to.x-size*Math.cos(angle+.45)},${to.y-size*Math.sin(angle+.45)}`);svg.append(arrow)}if(edge.label){const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',(from.x+to.x)/2);label.setAttribute('y',(from.y+to.y)/2-6);label.textContent=edge.label;svg.append(label)}}
  stage.append(svg);
  for(const n of [...nodes].sort((a,b)=>(a.type==='group'?-1:0)-(b.type==='group'?-1:0))){const card=document.createElement('section');card.className='canvas-node canvas-'+(['text','file','group','link'].includes(n.type)?n.type:'unknown');card.style.cssText=`left:${n.x-left}px;top:${n.y-top}px;width:${n.width}px;height:${n.height}px`;if(/^[1-6]$/.test(n.color||''))card.dataset.color=n.color;if(n.type==='text'){card.innerHTML=markdown(n.text||'')}else{const title=document.createElement('span');title.textContent=n.label||n.file||n.url||'Неподдерживаемый элемент';card.append(title)}stage.append(card)}
  container.append(stage);return container;
}
