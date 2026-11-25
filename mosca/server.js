'use strict';
const mosca = require('mosca');
const crypto = require('crypto');
const server = new mosca.Server({port:1883,stats:false});
const secret = process.env.MQTT_PASSWORD;
if (!secret) throw new Error('MQTT_PASSWORD is required');
function equal(a,b){const x=Buffer.from(a),y=Buffer.from(b);return x.length===y.length&&crypto.timingSafeEqual(x,y)}
server.authenticate=(client,user,password,done)=>{
  const name=String(user||'');
  const valid=/^(engine|manager|api|BOT-[A-Za-z0-9_-]+)$/.test(name)&&equal(String(password||''),secret);
  if(valid) client.identity=name;
  done(null,valid);
};
server.authorizePublish=(client,topic,payload,done)=>{
  let allowed=false;
  try{
    const m=JSON.parse(payload.toString()),parts=topic.split('/');
    const identity=client.identity;
    if(parts[0]==='ai-agent'&&payload.length<=65536){
      if(identity==='engine') allowed=true;
      else if(identity==='api') allowed=false;
      else if(identity==='manager') allowed=(parts[2]==='manager'||topic==='ai-agent/system/status')&&['manager','MANAGER'].includes(m.source_agent);
      else allowed=m.source_agent===identity&&((parts[2]===identity&&parts[3]!=='command')||(topic==='ai-agent/system/status'&&m.event==='HEARTBEAT'));
    }
  }catch(e){allowed=false}
  done(null,allowed);
};
server.authorizeSubscribe=(client,topic,done)=>{
  const allowed=['engine','manager','api'].includes(client.identity)?topic==='ai-agent/#':topic===`ai-agent/+/${client.identity}/command`;
  done(null,allowed);
};
server.on('ready',()=>console.log(JSON.stringify({service:'mosca',status:'ONLINE',port:1883})));
server.on('error',err=>console.error(JSON.stringify({service:'mosca',error:err.message})));
process.on('SIGTERM',()=>server.close(()=>process.exit(0)));
