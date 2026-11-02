// Native local web gateway. Python stays on loopback; forwarded client identity
// is always overwritten here and trusted by Python only from loopback.
'use strict';
const http = require('node:http');
let stopping=false;
const server = http.createServer((req,res)=>{
  const client=(req.socket.remoteAddress||'').replace(/^::ffff:/,'');
  const headers={...req.headers,'x-forwarded-for':client,'x-forwarded-proto':'http'};
  delete headers.forwarded;
  delete headers['x-real-ip'];
  let size=0;
  const upstream=http.request({hostname:'127.0.0.1',port:8766,path:req.url,method:req.method,headers,timeout:25000}, response=>{
    res.writeHead(response.statusCode,response.headers);
    response.pipe(res);
  });
  req.on('data',chunk=>{size+=chunk.length;if(size>32768){upstream.destroy();res.writeHead(413);res.end('Request too large');req.destroy();}});
  upstream.on('timeout',()=>upstream.destroy());
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(503,{'Content-Type':'text/plain'});res.end('Watchyard is starting. Please refresh shortly.');});
  req.on('aborted',()=>upstream.destroy());
  res.on('close',()=>upstream.destroy());
  req.pipe(upstream);
});
server.requestTimeout=30000;
server.headersTimeout=10000;
server.listen(8765,'0.0.0.0',()=>console.log('Watchyard home gateway listening on port 8765'));
function stop(){if(stopping)return;stopping=true;server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),3000).unref();}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
