import http from 'node:http';
import fs from 'node:fs';
const page=fs.readFileSync(new URL('./index.html',import.meta.url));
const frontPort=Number(process.env.MLX_STUDIO_FRONT_PORT||18000);
const backPort=Number(process.env.MLX_STUDIO_BACK_PORT||18002);
const server=http.createServer((req,res)=>{
  const path=(req.url||'/').split('?')[0];
  if((req.method==='GET'||req.method==='HEAD')&&path==='/'){
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Content-Length':page.length,'Cache-Control':'no-store','X-MLX-Studio-Fix':'chat-idle-30m'});
    return res.end(req.method==='HEAD'?undefined:page);
  }
  const upstream=http.request({hostname:'127.0.0.1',port:backPort,path:req.url,method:req.method,headers:req.headers},reply=>{
    res.writeHead(reply.statusCode||502,reply.headers);res.flushHeaders();reply.pipe(res);
    reply.on('error',()=>res.destroy());
  });
  upstream.on('error',err=>{if(!res.headersSent){res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{message:'Local model service unavailable',type:'server_error'}}))}else res.destroy()});
  req.on('aborted',()=>upstream.destroy());res.on('close',()=>{if(!res.writableEnded)upstream.destroy()});req.pipe(upstream);
});
server.on('upgrade',(req,socket,head)=>{
  const upstream=http.request({hostname:'127.0.0.1',port:backPort,path:req.url,method:req.method,headers:req.headers});
  upstream.on('upgrade',(reply,remote,remoteHead)=>{
    socket.write(`HTTP/1.1 ${reply.statusCode} ${reply.statusMessage}\r\n`+Object.entries(reply.headers).map(([k,v])=>`${k}: ${v}\r\n`).join('')+'\r\n');
    if(remoteHead.length)socket.write(remoteHead);if(head.length)remote.write(head);socket.pipe(remote).pipe(socket);
    socket.on('error',()=>remote.destroy());remote.on('error',()=>socket.destroy());socket.on('close',()=>remote.destroy());remote.on('close',()=>socket.destroy());
  });
  upstream.on('response',()=>{socket.end('HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n')});upstream.on('error',()=>socket.destroy());upstream.end();
});
server.requestTimeout=0;server.timeout=0;server.headersTimeout=60000;
server.listen(frontPort,'127.0.0.1',()=>console.log(`MLX Studio frontend fix listening on127.0.0.1:${server.address().port}; native backend127.0.0.1:${backPort}`));
process.on('SIGTERM',()=>server.close(()=>process.exit(0)));
