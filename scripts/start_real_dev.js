const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const serverDir = path.join(root, 'output', 'server');
fs.mkdirSync(serverDir, { recursive: true });
const requestedBackendPort = Number(process.env.COPILOT_BACKEND_PORT || '8029');
const requestedFrontendPort = Number(process.env.COPILOT_FRONTEND_PORT || '4261');

function canListen(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

async function findPort(start) {
  for (let port = start; port < start + 50; port += 1) {
    if (await canListen(port)) return String(port);
  }
  throw new Error(`No available port found from ${start} to ${start + 49}`);
}

function start(command, args, options, logName) {
  const log = fs.openSync(path.join(serverDir, logName), 'a');
  const child = spawn(command, args, {
    ...options,
    stdio: ['ignore', log, log],
    shell: process.platform === 'win32',
    windowsHide: true,
  });
  return child;
}

(async () => {
  const backendPort = await findPort(requestedBackendPort);
  const frontendPort = await findPort(requestedFrontendPort);

  const backend = start(
    'python',
    ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', backendPort, '--log-level', 'info'],
    { cwd: root, env: { ...process.env } },
    `real-backend-${backendPort}.log`,
  );

  const frontend = start(
    'npm',
    ['run', 'dev', '--', '--host', '127.0.0.1', '--port', frontendPort, '--strictPort'],
    {
      cwd: path.join(root, 'frontend'),
      env: {
        ...process.env,
        VITE_API_BASE_URL: '',
        VITE_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
      },
    },
    `real-frontend-${frontendPort}.log`,
  );

  console.log(JSON.stringify({
    backendPid: backend.pid,
    frontendPid: frontend.pid,
    requestedFrontend: `http://127.0.0.1:${requestedFrontendPort}`,
    requestedBackend: `http://127.0.0.1:${requestedBackendPort}`,
    frontend: `http://127.0.0.1:${frontendPort}`,
    backend: `http://127.0.0.1:${backendPort}`,
  }, null, 2));

  const stop = () => {
    for (const child of [frontend, backend]) {
      if (!child.killed) child.kill();
    }
    process.exit(0);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  backend.on('exit', (code) => {
    if (code) console.error(`Backend exited with code ${code}. See output/server/real-backend-${backendPort}.log`);
  });
  frontend.on('exit', (code) => {
    if (code) console.error(`Frontend exited with code ${code}. See output/server/real-frontend-${frontendPort}.log`);
  });
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
