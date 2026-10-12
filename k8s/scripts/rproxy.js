#!/usr/bin/env node
// CONNECT-only 代理：kind 节点内 containerd 经 host.docker.internal:3128 出网拉镜像。
// 用法：node rproxy.js  （默认监听 0.0.0.0:3128，可用 PORT 覆盖）
const net = require('net');

const PORT = parseInt(process.env.PORT || '3128', 10);

const server = net.createServer((client) => {
  client.once('error', () => client.destroy());
  let head = Buffer.alloc(0);
  client.on('data', function onData(chunk) {
    head = Buffer.concat([head, chunk]);
    const idx = head.indexOf('\r\n\r\n');
    if (idx === -1) {
      if (head.length > 8192) client.destroy();
      return;
    }
    client.removeListener('data', onData);
    const firstLine = head.slice(0, idx).toString().split('\r\n')[0];
    const m = /^CONNECT\s+(\S+):(\d+)\s+HTTP/i.exec(firstLine);
    if (!m) {
      client.end('HTTP/1.1 405 Only CONNECT allowed\r\n\r\n');
      return;
    }
    const upstream = net.connect({ host: m[1], port: parseInt(m[2], 10) }, () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      const rest = head.slice(idx + 4);
      if (rest.length) upstream.write(rest);
      client.pipe(upstream);
      upstream.pipe(client);
    });
    upstream.once('error', () => client.destroy());
    client.once('close', () => upstream.destroy());
    upstream.once('close', () => client.destroy());
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`rproxy listening on 0.0.0.0:${PORT} (CONNECT only)`);
});
