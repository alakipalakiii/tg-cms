// Configure the same secret in Telegram before activating this guard in production.
export function telegramWebhookRejection(request: Request, secret: string | undefined): number | null {
  if (!secret || !/^[A-Za-z0-9_-]{1,256}$/.test(secret)) return 503;
  const supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token') || '';
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(supplied) || supplied.length !== secret.length) return 401;
  const encoder = new TextEncoder();
  return crypto.subtle.timingSafeEqual(encoder.encode(secret), encoder.encode(supplied)) ? null : 401;
}
