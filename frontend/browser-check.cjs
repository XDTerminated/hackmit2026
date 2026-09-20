const { chromium } = require('playwright');

(async () => {
  const frontendUrl = process.env.FRONTEND_URL || 'http://127.0.0.1:3000';
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-sandbox'] });
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const research = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const failures = [];
  for (const page of [phone, research]) page.on('pageerror', (e) => failures.push(e.message));
  await phone.request.post(`${backendUrl}/api/demo/reset`);
  await Promise.all([phone.goto(`${frontendUrl}/`), research.goto(`${frontendUrl}/research`)]);
  await phone.getByRole('button', { name: 'Start monitoring' }).click();
  await phone.getByRole('heading', { name: 'Monitoring your gait' }).waitFor();
  if (process.env.CAPTURE_SCREENSHOTS === '1') {
    await phone.screenshot({ path: '/private/tmp/stride-home.png' });
    await research.screenshot({ path: '/private/tmp/stride-research.png' });
  }
  const sequence = ['Possible interruption', 'Rhythmic cue active', 'Movement resuming', 'Walking resumed'];
  await research.getByRole('button', { name: /Trigger event/i }).click();
  for (const label of sequence) await phone.getByRole('heading', { name: label }).waitFor({ timeout: 9000 });
  await phone.getByRole('heading', { name: 'Monitoring your gait' }).waitFor({ timeout: 9000 });
  for (const size of [{ width: 390, height: 844 }, { width: 375, height: 812 }, { width: 430, height: 932 }]) {
    await phone.setViewportSize(size);
    const overflow = await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) failures.push(`overflow ${size.width}`);
  }
  await phone.goto(`${frontendUrl}/activity`);
  await phone.getByText('Movement interruption', { exact: true }).first().waitFor({ timeout: 5000 });
  const activity = await phone.getByText('Movement interruption', { exact: true }).count();
  await phone.goto(`${frontendUrl}/device`);
  const device = await phone.getByRole('heading', { name: 'Wearable' }).count();
  await phone.goto(`${frontendUrl}/`);
  await phone.getByRole('heading', { name: 'Monitoring your gait' }).waitFor();
  for (let i = 0; i < 4; i++) {
    await research.getByRole('button', { name: /Trigger event/i }).click();
    for (const label of sequence) await phone.getByRole('heading', { name: label }).waitFor({ timeout: 9000 });
    await phone.getByRole('heading', { name: 'Monitoring your gait' }).waitFor({ timeout: 9000 });
  }
  await research.getByRole('button', { name: /Reset/i }).click();
  await phone.getByRole('heading', { name: 'Ready when you are' }).waitFor({ timeout: 5000 });
  await phone.goto(`${frontendUrl}/device`);
  await phone.getByRole('button', { name: 'Start calibration' }).click();
  await phone.getByRole('heading', { name: 'Baseline ready' }).waitFor({ timeout: 14000 });
  await research.getByRole('tab', { name: 'REPLAY' }).click();
  await research.getByRole('button', { name: /Replay labeled event/i }).click();
  await research.getByText('Detection/cue overlay simulated', { exact: false }).waitFor({ timeout: 5000 });
  await research.getByRole('heading', { name: 'POSSIBLE FREEZE' }).waitFor({ timeout: 10000 });
  await research.getByRole('heading', { name: 'RECOVERED' }).waitFor({ timeout: 10000 });
  await research.getByRole('heading', { name: 'READY' }).waitFor({ timeout: 10000 });
  await research.getByRole('tab', { name: 'LIVE' }).click();
  await research.request.post(`${backendUrl}/api/imu`, { data: { timestamp: 500, ax: 0, ay: 0, az: 9.81, gx: 1, gy: 0, gz: 0 } });
  await research.getByText('DEVICE CONNECTED', { exact: false }).first().waitFor({ timeout: 5000 });
  console.log(JSON.stringify({ runs: 5, sequence, activity, device, calibration: true, replay: true, live: true, failures }));
  await browser.close();
  if (failures.length || !activity || !device) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
