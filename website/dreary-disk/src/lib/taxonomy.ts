export type MahoonCategory = {
  title: string;
  aliases: string[];
  tags: string[];
};

const AUDIO_BOOK_TAGS = [
  "کتاب_گویا",
  "کتاب‌گویا",
  "کتابگویا",
  "کتاب_صوتی",
  "کتاب‌صوتی",
  "کتابصوتی"
];

export const MAHOON_CATEGORIES: MahoonCategory[] = [
  {
    title: "کتاب",
    aliases: ["کتاب"],
    tags: ["کتاب", ...AUDIO_BOOK_TAGS]
  },
  {
    title: "دیالوگ ها",
    aliases: ["دیالوگ ها", "دیالوگ‌ها", "دیالوگ_ها", "دیالوگها", "دیالوگ"],
    tags: ["دیالوگ", "دیالوگ‌ها", "دیالوگ_ها", "دیالوگها"]
  },
  {
    title: "صوتی",
    aliases: ["صوتی", "صدا", "موسیقی"],
    tags: ["صوتی", "صدا", "موسیقی", ...AUDIO_BOOK_TAGS]
  },
  {
    title: "شعر و متن",
    aliases: ["شعر و متن", "متن", "متن‌ها", "متن_ها", "متنها", "شعر", "اشعار", "شعرها", "شعر_ها"],
    tags: [
      "متن",
      "متن‌ها",
      "متن_ها",
      "متنها",
      "شعر",
      "اشعار",
      "شعرها",
      "شعر_ها"
    ]
  },
  {
    title: "نقاشی",
    aliases: ["نقاشی"],
    tags: ["نقاشی"]
  }
];

export function normalizeMahoonTaxonomyToken(
  value: string | null | undefined
): string {
  return String(value || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u200c\u200f]/g, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export function findMahoonCategory(
  value: string | null | undefined
): MahoonCategory | null {
  const normalized = normalizeMahoonTaxonomyToken(value);

  return MAHOON_CATEGORIES.find((category) =>
    category.aliases.some(
      (alias) => normalizeMahoonTaxonomyToken(alias) === normalized
    )
  ) || null;
}

export const MAHOON_CATEGORY_TAGS = new Set(
  MAHOON_CATEGORIES.flatMap((category) => category.tags)
    .map(normalizeMahoonTaxonomyToken)
);
