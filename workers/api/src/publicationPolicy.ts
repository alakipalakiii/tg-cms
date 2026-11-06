export const DEFAULT_PUBLICATION_TAGS = ['کتاب', 'کتاب_گویا', 'کتاب_صوتی', 'دیالوگ', 'دیالوگ_ها', 'صوتی', 'صدا', 'موسیقی', 'متن', 'متن_ها', 'شعر', 'اشعار', 'شعرها', 'نقاشی'];
const POLICY_KEY = 'publication_policy_v1';
type Policy = { revision: number; allowed_tags: string[]; auto_publish: boolean };

export function normalizePublicationTag(value: string): string {
  return value.normalize('NFKC').replace(/^#/, '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/[_\u200c]/g, '').toLowerCase();
}

export function publicationAllowed(text: string, policy: Policy): boolean {
  const allowed = new Set(policy.allowed_tags.map(normalizePublicationTag));
  return [...String(text || '').replace(/https?:\/\/\S+/giu, ' ').matchAll(/(?:^|[^\p{L}\p{N}_\u200c])#([\p{L}\p{N}_\u200c]+)/gu)]
    .some(match => allowed.has(normalizePublicationTag(match[1])));
}

export function validatePublicationPolicy(value: unknown, revision = 0): Policy {
  const input = value as Partial<Policy>;
  if (!input || !Array.isArray(input.allowed_tags) || input.allowed_tags.length > 50 || typeof input.auto_publish !== 'boolean') {
    throw new Error('قانون انتشار معتبر نیست. حداکثر ۵۰ هشتگ وارد کنید.');
  }
  const tags = input.allowed_tags.map(tag => {
    if (typeof tag !== 'string' || !/^#?[\p{L}\p{N}_\u200c]{1,60}$/u.test(tag.trim())) throw new Error('هر هشتگ باید یک واژه، بدون فاصله و بدون لینک باشد.');
    return tag.trim().replace(/^#/, '');
  });
  return { revision, allowed_tags: [...new Map(tags.map(tag => [normalizePublicationTag(tag), tag])).values()], auto_publish: input.auto_publish };
}

export async function readPublicationPolicy(env): Promise<Policy> {
  const row = await env.DB.prepare('SELECT value FROM site_settings WHERE key = ? LIMIT 1').bind(POLICY_KEY).first();
  if (!row) return { revision: 0, allowed_tags: [...DEFAULT_PUBLICATION_TAGS], auto_publish: true };
  const stored = JSON.parse(row.value);
  if (!Number.isSafeInteger(stored.revision) || stored.revision < 1) throw new Error('Publication policy unavailable');
  return validatePublicationPolicy(stored, stored.revision);
}

export async function publicationRejection(env, text: string): Promise<boolean> {
  return !publicationAllowed(text, await readPublicationPolicy(env));
}

export async function handlePublicationPolicy(request: Request, env) {
  if (request.method === 'GET') return { policy: await readPublicationPolicy(env), channel_deletion: { available: false, reason: 'BOT_API_HAS_NO_CHANNEL_DELETE_UPDATE' } };
  const body = await request.json() as { policy: unknown; expected_revision: number };
  const current = await readPublicationPolicy(env);
  const policy = validatePublicationPolicy(body.policy, current.revision + 1);
  // The same bounded snapshot drives both preview and the confirmed, atomic update.
  const { results } = await env.DB.prepare("SELECT id, text FROM posts WHERE deleted_at IS NULL AND COALESCE(is_published, 1) = 1 LIMIT 10001").all();
  if (results.length > 10000) throw new Error('برای بیش از ده هزار مطلب، بررسی دسته‌ای لازم است.');
  const affected = results.filter(post => !publicationAllowed(post.text, policy)).map(post => Number(post.id));
  if (request.method === 'POST') return { policy, affected_count: affected.length, affected_ids: affected.slice(0, 20) };
  if (request.method !== 'PATCH') throw new Error('Unsupported publication policy operation');
  if (body.expected_revision !== current.revision) return { conflict: true };
  const serialized = JSON.stringify(policy);
  const statements = [env.DB.prepare(`INSERT INTO site_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    WHERE json_extract(site_settings.value, '$.revision') = ?`).bind(POLICY_KEY, serialized, current.revision)];
  for (let offset = 0; offset < affected.length; offset += 100) {
    const ids = affected.slice(offset, offset + 100);
    statements.push(env.DB.prepare(`UPDATE posts SET is_published = 0, updated_at = CURRENT_TIMESTAMP
      WHERE id IN (${ids.map(() => '?').join(',')}) AND deleted_at IS NULL
      AND EXISTS (SELECT 1 FROM site_settings WHERE key = ? AND value = ?)`).bind(...ids, POLICY_KEY, serialized));
  }
  const result = await env.DB.batch(statements);
  if (!result[0].meta.changes) return { conflict: true };
  return { policy, unpublished_count: result.slice(1).reduce((sum, r) => sum + Number(r.meta.changes || 0), 0) };
}
