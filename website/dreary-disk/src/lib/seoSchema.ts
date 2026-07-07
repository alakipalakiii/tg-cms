import { SITE } from "../config";

type SchemaObject = Record<string, unknown>;

type ArticleSchemaInput = {
  title?: string | null;
  description?: string | null;
  url?: string | null;
  image?: string | null;
  datePublished?: string | null;
  dateModified?: string | null;
  body?: string | null;
};

function baseUrl(): string {
  return SITE.url.replace(/\/+$/, "");
}

export function absoluteUrl(value?: string | null): string {
  const source = String(value || "").trim();

  if (!source) return "";

  if (/^https?:\/\//i.test(source)) {
    return source;
  }

  return baseUrl() + "/" + source.replace(/^\/+/, "");
}

function cleanText(value?: string | null, maxLength = 500): string {
  return String(value || "")
    .replace(/\u{1F539}?\s*@mahoonartmagazine/giu, "")
    .replace(/\u{1F539}/gu, "")
    .replace(/(^|\n)\s*(?:🎥|🎬|فیلم\s*:?)\s*#?\s*[^\n]+/giu, "\n")
    .replace(/https?:\/\/(?:t\.me|telegram\.me|telegram\.dog)\/[^\s]+/giu, "")
    .replace(/https?:\/\/[^\s]+/giu, "")
    .replace(/@[a-zA-Z0-9_]+/g, "")
    .replace(/(^|\s)#([^\s#]+)/gu, " ")
    .replace(/[•●▪▫◦]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength)
    .trim();
}

function toIsoDate(value?: string | null): string {
  if (!value) return new Date().toISOString();

  const source = String(value).includes("T")
    ? String(value)
    : String(value).replace(" ", "T") + "Z";

  const parsed = new Date(source);

  if (Number.isNaN(parsed.getTime())) {
    return new Date().toISOString();
  }

  return parsed.toISOString();
}

function compactObject<T extends SchemaObject>(input: T): T {
  const output: SchemaObject = {};

  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;

    output[key] = value;
  }

  return output as T;
}

export function organizationSchema(): SchemaObject {
  const url = baseUrl();

  return compactObject({
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": url + "/#organization",
    name: SITE.name,
    url,
    logo: {
      "@type": "ImageObject",
      url: absoluteUrl(SITE.logo)
    },
    sameAs: [SITE.telegramUrl].filter(Boolean)
  });
}

export function websiteSchema(): SchemaObject {
  const url = baseUrl();

  return compactObject({
    "@context": "https://schema.org",
    "@type": "WebSite",
    "@id": url + "/#website",
    name: SITE.name,
    alternateName: "Mahoon Art Magazine",
    url,
    description: SITE.description,
    inLanguage: "fa-IR",
    publisher: {
      "@id": url + "/#organization"
    }
  });
}

export function makeArticleSchema(input: ArticleSchemaInput): SchemaObject {
  const url = String(input.url || baseUrl()).trim();
  const imageUrl = absoluteUrl(input.image || SITE.defaultImage);
  const title = cleanText(input.title, 110) || SITE.name;
  const description = cleanText(input.description || input.body, 240) || SITE.description;

  return compactObject({
    "@context": "https://schema.org",
    "@type": "Article",
    "@id": url + "#article",
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": url
    },
    headline: title,
    description,
    image: imageUrl ? [imageUrl] : undefined,
    datePublished: toIsoDate(input.datePublished),
    dateModified: toIsoDate(input.dateModified || input.datePublished),
    author: {
      "@id": baseUrl() + "/#organization"
    },
    publisher: {
      "@id": baseUrl() + "/#organization"
    },
    isPartOf: {
      "@id": baseUrl() + "/#website"
    },
    inLanguage: "fa-IR",
    articleBody: cleanText(input.body, 5000)
  });
}

export function stringifySchema(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
