(() => {
  const $ = (id) => document.getElementById(id);
  const ids = ["capacity","refill","windowLimit","windowSeconds","requestCount","intervalMs","baseDelay","maxDelay","strategy","jitter"];
  const defaults = {capacity:10,refill:2,windowLimit:8,windowSeconds:2,requestCount:24,intervalMs:120,baseDelay:1,maxDelay:30,strategy:"exponential",jitter:"none"};

  function readConfig(){
    const c={};
    for(const id of ids){const el=$(id); c[id]=el.tagName==="SELECT"?el.value:Number(el.value);}
    return c;
  }
  function validate(c){
    if(["capacity","windowLimit","windowSeconds","requestCount"].some(k=>!Number.isFinite(c[k])||c[k]<=0)) return "Capacity, limits, window and requests must be greater than zero.";
    if(["refill","intervalMs","baseDelay","maxDelay"].some(k=>!Number.isFinite(c[k])||c[k]<0)) return "Refill, interval and delay values cannot be negative.";
    if(c.maxDelay<c.baseDelay) return "Max delay must be at least the base delay.";
    if(c.requestCount>1000) return "Request count is capped at 1,000.";
    return "";
  }
  function fib(n){let a=0,b=1;for(let i=0;i<n;i++) [a,b]=[b,a+b];return a;}
  function rawDelay(c,i){if(c.strategy==="linear") return c.baseDelay*(i+1);if(c.strategy==="fibonacci") return c.baseDelay*fib(i+2);return c.baseDelay*(2**i);}
  function jitter(c,raw,prev){
    const cap=Math.min(raw,c.maxDelay);
    if(c.jitter==="none") return cap;
    if(c.jitter==="full") return Math.random()*cap;
    if(c.jitter==="equal") return cap/2+Math.random()*cap/2;
    const prior=prev==null?c.baseDelay:Math.max(c.baseDelay,prev);
    const upper=Math.min(c.maxDelay,Math.max(c.baseDelay,prior*3));
    return c.baseDelay+Math.random()*Math.max(0,upper-c.baseDelay);
  }
  function backoff(c){const out=[];let prev=null;for(let i=0;i<6;i++){const d=jitter(c,rawDelay(c,i),prev);out.push(d);prev=d;}return out;}
  function simulate(c){
    let tokens=c.capacity,last=0,allowed=0,throttled=0;const window=[],events=[];
    for(let i=0;i<c.requestCount;i++){
      const now=i*c.intervalMs/1000;tokens=Math.min(c.capacity,tokens+Math.max(0,now-last)*c.refill);last=now;
      while(window.length&&window[0]<=now-c.windowSeconds) window.shift();
      let ok=true,reason="Allowed";
      if(tokens<1){ok=false;reason="Token bucket empty";}
      else if(window.length>=c.windowLimit){ok=false;reason="Sliding window reached";}
      if(ok){tokens-=1;window.push(now);allowed++;}else throttled++;
      if(events.length<7||i===c.requestCount-1) events.push({index:i+1,time:now,ok,reason});
    }
    return {allowed,throttled,tokens,events};
  }
  function renderBars(values){
    const root=$("bars");root.replaceChildren();const peak=Math.max(...values,.001);
    values.forEach((v,i)=>{const wrap=document.createElement("div");wrap.className="bar-wrap";const bar=document.createElement("div");bar.className="bar";bar.style.height=Math.max(4,v/peak*100)+"%";const val=document.createElement("span");val.textContent=v.toFixed(v<10?2:1)+"s";bar.append(val);const lab=document.createElement("small");lab.textContent="#"+(i+1);wrap.append(bar,lab);root.append(wrap);});
  }
  function renderTimeline(events){
    const root=$("timeline");root.replaceChildren();events.forEach(e=>{const row=document.createElement("div");row.className="event"+(e.ok?"":" blocked");row.innerHTML=`<time>${e.time.toFixed(2)}s</time><span class="dot"></span><span>Request ${e.index} · ${e.reason}</span><b>${e.ok?"ALLOW":"BLOCK"}</b>`;root.append(row);});
  }
  function run(ev){
    ev?.preventDefault();const c=readConfig(),err=validate(c);$("error").textContent=err;if(err)return;
    const sim=simulate(c),bo=backoff(c);
    $("allowed").textContent=sim.allowed;$("throttled").textContent=sim.throttled;$("tokens").textContent=sim.tokens.toFixed(1);$("peak").textContent=Math.max(...bo).toFixed(2)+"s";
    $("status").textContent=sim.throttled?"Throttling detected":"Within limits";renderBars(bo);renderTimeline(sim.events);
  }
  $("sim-form").addEventListener("submit",run);
  $("reset").addEventListener("click",()=>{for(const [k,v] of Object.entries(defaults)) $(k).value=v;run();});
  $("theme").addEventListener("click",()=>{const next=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=next;localStorage.setItem("rl-theme",next);});
  const saved=localStorage.getItem("rl-theme");if(saved) document.documentElement.dataset.theme=saved;
  run();
})();