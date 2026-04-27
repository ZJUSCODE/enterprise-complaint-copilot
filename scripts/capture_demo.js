const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const zlib = require('node:zlib');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const outputDir = path.join(root, 'output', 'playwright');
fs.mkdirSync(outputDir, { recursive: true });

const requestedBackendPort = Number(process.env.COPILOT_CAPTURE_BACKEND_PORT || 8029);
const requestedFrontendPort = Number(process.env.COPILOT_CAPTURE_FRONTEND_PORT || 4261);

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

async function findAvailablePort(startPort, reserved = new Set()) {
  for (let port = startPort; port < startPort + 50; port += 1) {
    if (reserved.has(port)) continue;
    if (await isPortAvailable(port)) return port;
  }
  throw new Error(`No available local port found from ${startPort}`);
}

function waitFor(url, timeoutMs = 90000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
        } else {
          retry();
        }
      });
      req.on('error', retry);
      req.setTimeout(3000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
      } else {
        setTimeout(tick, 1000);
      }
    };
    tick();
  });
}

function spawnLogged(command, args, options) {
  const child = spawn(command, args, {
    ...options,
    env: { ...process.env, ...options.env },
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: process.platform === 'win32',
  });
  child.stdout.on('data', (chunk) => process.stdout.write(chunk));
  child.stderr.on('data', (chunk) => process.stderr.write(chunk));
  return child;
}

function killTree(child) {
  if (!child?.pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    child.kill('SIGTERM');
  }
}

function paethPredictor(left, up, upLeft) {
  const estimate = left + up - upLeft;
  const leftDistance = Math.abs(estimate - left);
  const upDistance = Math.abs(estimate - up);
  const upLeftDistance = Math.abs(estimate - upLeft);
  if (leftDistance <= upDistance && leftDistance <= upLeftDistance) return left;
  if (upDistance <= upLeftDistance) return up;
  return upLeft;
}

function decodePng(buffer) {
  const signature = '89504e470d0a1a0a';
  if (buffer.subarray(0, 8).toString('hex') !== signature) {
    throw new Error('Only PNG screenshots can be converted to GIF');
  }

  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let interlace = 0;
  const idatChunks = [];

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString('ascii', offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;

    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === 'IDAT') {
      idatChunks.push(data);
    } else if (type === 'IEND') {
      break;
    }
  }

  if (bitDepth !== 8 || interlace !== 0) {
    throw new Error(`Unsupported PNG format: bitDepth=${bitDepth}, interlace=${interlace}`);
  }

  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : 0;
  if (!channels) {
    throw new Error(`Unsupported PNG color type: ${colorType}`);
  }

  const inflated = zlib.inflateSync(Buffer.concat(idatChunks));
  const stride = width * channels;
  const rgba = Buffer.alloc(width * height * 4);
  let inputOffset = 0;
  let outputOffset = 0;
  let previous = Buffer.alloc(stride);

  for (let y = 0; y < height; y += 1) {
    const filter = inflated[inputOffset];
    inputOffset += 1;
    const row = Buffer.from(inflated.subarray(inputOffset, inputOffset + stride));
    inputOffset += stride;

    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? row[x - channels] : 0;
      const up = previous[x] || 0;
      const upLeft = x >= channels ? previous[x - channels] || 0 : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      else if (filter === 2) predictor = up;
      else if (filter === 3) predictor = Math.floor((left + up) / 2);
      else if (filter === 4) predictor = paethPredictor(left, up, upLeft);
      else if (filter !== 0) throw new Error(`Unsupported PNG filter: ${filter}`);
      row[x] = (row[x] + predictor) & 0xff;
    }

    for (let x = 0; x < width; x += 1) {
      const source = x * channels;
      if (channels === 4) {
        rgba[outputOffset++] = row[source];
        rgba[outputOffset++] = row[source + 1];
        rgba[outputOffset++] = row[source + 2];
        rgba[outputOffset++] = row[source + 3];
      } else if (channels === 3) {
        rgba[outputOffset++] = row[source];
        rgba[outputOffset++] = row[source + 1];
        rgba[outputOffset++] = row[source + 2];
        rgba[outputOffset++] = 255;
      } else {
        rgba[outputOffset++] = row[source];
        rgba[outputOffset++] = row[source];
        rgba[outputOffset++] = row[source];
        rgba[outputOffset++] = 255;
      }
    }
    previous = row;
  }

  return { width, height, rgba };
}

function resizeImage(image, maxWidth) {
  if (image.width <= maxWidth) return image;
  const width = maxWidth;
  const height = Math.round((image.height * width) / image.width);
  const rgba = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    const sourceY = Math.min(image.height - 1, Math.floor((y * image.height) / height));
    for (let x = 0; x < width; x += 1) {
      const sourceX = Math.min(image.width - 1, Math.floor((x * image.width) / width));
      const source = (sourceY * image.width + sourceX) * 4;
      const target = (y * width + x) * 4;
      rgba[target] = image.rgba[source];
      rgba[target + 1] = image.rgba[source + 1];
      rgba[target + 2] = image.rgba[source + 2];
      rgba[target + 3] = image.rgba[source + 3];
    }
  }
  return { width, height, rgba };
}

function buildPalette() {
  const palette = Buffer.alloc(256 * 3);
  for (let red = 0; red < 8; red += 1) {
    for (let green = 0; green < 8; green += 1) {
      for (let blue = 0; blue < 4; blue += 1) {
        const index = (red << 5) | (green << 2) | blue;
        palette[index * 3] = Math.round((red * 255) / 7);
        palette[index * 3 + 1] = Math.round((green * 255) / 7);
        palette[index * 3 + 2] = Math.round((blue * 255) / 3);
      }
    }
  }
  return palette;
}

function quantizeToIndexed(image) {
  const indexed = Buffer.alloc(image.width * image.height);
  for (let pixel = 0; pixel < indexed.length; pixel += 1) {
    const rgbaOffset = pixel * 4;
    const alpha = image.rgba[rgbaOffset + 3];
    const red = alpha < 128 ? 255 : image.rgba[rgbaOffset];
    const green = alpha < 128 ? 255 : image.rgba[rgbaOffset + 1];
    const blue = alpha < 128 ? 255 : image.rgba[rgbaOffset + 2];
    indexed[pixel] = ((red >> 5) << 5) | ((green >> 5) << 2) | (blue >> 6);
  }
  return indexed;
}

function writeCode(bytes, state, code) {
  state.bitBuffer |= code << state.bitCount;
  state.bitCount += 9;
  while (state.bitCount >= 8) {
    bytes.push(state.bitBuffer & 0xff);
    state.bitBuffer >>= 8;
    state.bitCount -= 8;
  }
}

function lzwEncodeUncompressed(indices) {
  const clearCode = 256;
  const endCode = 257;
  const bytes = [];
  const state = { bitBuffer: 0, bitCount: 0 };
  let firstAfterClear = true;
  let codesSinceClear = 0;

  writeCode(bytes, state, clearCode);
  for (const index of indices) {
    if (!firstAfterClear && codesSinceClear >= 250) {
      writeCode(bytes, state, clearCode);
      firstAfterClear = true;
      codesSinceClear = 0;
    }
    writeCode(bytes, state, index);
    if (firstAfterClear) {
      firstAfterClear = false;
    } else {
      codesSinceClear += 1;
    }
  }
  writeCode(bytes, state, endCode);
  if (state.bitCount > 0) {
    bytes.push(state.bitBuffer & 0xff);
  }
  return Buffer.from(bytes);
}

function uint16(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function dataBlocks(buffer) {
  const chunks = [];
  for (let offset = 0; offset < buffer.length; offset += 255) {
    const chunk = buffer.subarray(offset, offset + 255);
    chunks.push(Buffer.from([chunk.length]));
    chunks.push(chunk);
  }
  chunks.push(Buffer.from([0]));
  return Buffer.concat(chunks);
}

function encodeGif(frames, width, height) {
  const chunks = [
    Buffer.from('GIF89a', 'ascii'),
    uint16(width),
    uint16(height),
    Buffer.from([0xf7, 255, 0]),
    buildPalette(),
    Buffer.from([0x21, 0xff, 0x0b]),
    Buffer.from('NETSCAPE2.0', 'ascii'),
    Buffer.from([0x03, 0x01, 0x00, 0x00, 0x00]),
  ];

  for (const frame of frames) {
    const delay = Math.max(1, Math.round(frame.delayCs || 120));
    chunks.push(Buffer.from([0x21, 0xf9, 0x04, 0x08]));
    chunks.push(uint16(delay));
    chunks.push(Buffer.from([0x00, 0x00]));
    chunks.push(Buffer.from([0x2c]));
    chunks.push(uint16(0));
    chunks.push(uint16(0));
    chunks.push(uint16(width));
    chunks.push(uint16(height));
    chunks.push(Buffer.from([0x00, 0x08]));
    chunks.push(dataBlocks(lzwEncodeUncompressed(frame.indexed)));
  }
  chunks.push(Buffer.from([0x3b]));
  return Buffer.concat(chunks);
}

function writeDemoGif(frameBuffers, targetPath) {
  const frames = frameBuffers.map((frame) => {
    const image = resizeImage(decodePng(frame.buffer), 720);
    return { ...image, indexed: quantizeToIndexed(image), delayCs: frame.delayCs };
  });
  const first = frames[0];
  if (!first) return null;
  for (const frame of frames) {
    if (frame.width !== first.width || frame.height !== first.height) {
      throw new Error('All GIF frames must share the same dimensions');
    }
  }
  fs.writeFileSync(targetPath, encodeGif(frames, first.width, first.height));
  return targetPath;
}

async function captureState(page, name, frameBuffers, delayCs = 120) {
  const pngPath = path.join(outputDir, `${name}.png`);
  await page.screenshot({ path: pngPath, fullPage: false });
  frameBuffers.push({ buffer: await page.screenshot({ type: 'png', fullPage: false }), delayCs });
  return `output/playwright/${name}.png`;
}

(async () => {
  const backendPort = await findAvailablePort(requestedBackendPort);
  const frontendPort = await findAvailablePort(requestedFrontendPort, new Set([backendPort]));

  const backend = spawnLogged('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(backendPort)], {
    cwd: root,
    env: {
      AUTH_ENFORCED: 'true',
      REDIS_ENABLED: 'false',
      DATA_QUERY_BACKEND: 'sqlite',
      USE_LANGCHAIN_RAG: 'false',
      LLM_API_KEY: '',
      OPENAI_API_KEY: '',
      EMBEDDING_API_KEY: '',
      JWT_SECRET: 'demo-capture-secret',
    },
  });

  const frontend = spawnLogged('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(frontendPort)], {
    cwd: path.join(root, 'frontend'),
    env: {
      VITE_API_BASE_URL: '',
      VITE_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
    },
  });

  const browser = await chromium.launch();
  const frameBuffers = [];
  const screenshots = [];
  try {
    await waitFor(`http://127.0.0.1:${backendPort}/api/health`);
    await waitFor(`http://127.0.0.1:${frontendPort}`);

    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(`http://127.0.0.1:${frontendPort}/login`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.login-panel', { timeout: 30000 });
    screenshots.push(await captureState(page, 'v2-login', frameBuffers));

    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL(`**:${frontendPort}/`);
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('.workbench-hero', { timeout: 30000 });
    await page.waitForSelector('.queue-panel', { timeout: 30000 });
    screenshots.push(await captureState(page, 'v2-home', frameBuffers));

    await page.getByRole('link', { name: '处理', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.getByPlaceholder(/例如：/).fill('查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态');
    await page.getByRole('button', { name: '发送' }).click();
    await page.waitForSelector('.chat-message.assistant .runtime-meta', { timeout: 60000 });
    screenshots.push(await captureState(page, 'v2-copilot-logistics', frameBuffers, 180));

    const gifPath = writeDemoGif(frameBuffers, path.join(outputDir, 'copilot-demo.gif'));
    console.log(JSON.stringify({
      screenshots,
      gif: gifPath ? 'output/playwright/copilot-demo.gif' : null,
    }, null, 2));
  } finally {
    await browser.close().catch(() => {});
    killTree(backend);
    killTree(frontend);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
