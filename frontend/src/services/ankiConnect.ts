/**
 * AnkiConnect 通信层
 * AnkiConnect 默认监听 http://localhost:8765
 */

const ANKI_CONNECT_URL = 'http://localhost:8765';

interface AnkiConnectRequest {
  action: string;
  version: number;
  params?: Record<string, unknown>;
}

interface AnkiConnectResponse<T = unknown> {
  result: T;
  error: string | null;
}

async function ac<T = unknown>(action: string, params?: Record<string, unknown>): Promise<T> {
  const body: AnkiConnectRequest = { action, version: 6, params };
  const resp = await fetch(ANKI_CONNECT_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`AnkiConnect HTTP ${resp.status}`);
  }
  const data: AnkiConnectResponse<T> = await resp.json();
  if (data.error) {
    throw new Error(data.error);
  }
  return data.result;
}

/** 检测 Anki 是否在线 */
export async function pingAnki(): Promise<boolean> {
  try {
    const version = await ac<number>('version');
    return typeof version === 'number' && version >= 6;
  } catch {
    return false;
  }
}

/** 创建牌组（幂等） */
export async function createDeck(deckName: string): Promise<void> {
  await ac('createDeck', { deck: deckName });
}

/** 创建模型（幂等） */
export async function createModel(model: {
  modelName: string;
  inOrderFields: string[];
  css: string;
  cardTemplates: Array<{ Name: string; Front: string; Back: string }>;
}): Promise<void> {
  // 先检查模型是否已存在
  try {
    const models = await ac<Record<string, unknown>>('modelNames');
    if (Array.isArray(models) && models.includes(model.modelName)) {
      return; // 已存在，跳过
    }
  } catch {
    // 忽略，继续创建
  }
  await ac('createModel', {
    modelName: model.modelName,
    inOrderFields: model.inOrderFields,
    css: model.css,
    cardTemplates: model.cardTemplates,
  });
}

/** 将 URL 转为 base64 */
export async function urlToBase64(url: string): Promise<string> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`获取文件失败: ${resp.status}`);
  const blob = await resp.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      // 去掉 data:xxx;base64, 前缀
      const base64 = result.split(',')[1] || '';
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/** 上传媒体文件到 Anki */
export async function storeMediaFile(filename: string, base64Data: string): Promise<void> {
  await ac('storeMediaFile', { filename, data: base64Data });
}

/** 添加笔记 */
export async function addNote(note: {
  deckName: string;
  modelName: string;
  fields: Record<string, string>;
  options?: { allowDuplicate: boolean };
  tags?: string[];
}): Promise<number> {
  return await ac<number>('addNote', { note });
}

/** 按查询语句搜索笔记 ID */
export async function findNotes(query: string): Promise<number[]> {
  return await ac<number[]>('findNotes', { query });
}

/** 批量获取笔记详情 */
export async function notesInfo(noteIds: number[]): Promise<Array<{
  noteId: number;
  modelName: string;
  tags: string[];
  fields: Record<string, { value: string; order: number }>;
}>> {
  return await ac('notesInfo', { notes: noteIds });
}

/**
 * 从 Anki 的 ClipLingo 牌组中提取所有 Word 字段
 * 返回去重后的小写单词列表
 */
export async function fetchWordsFromAnki(): Promise<string[]> {
  // 搜索所有 ClipLingo 开头的牌组中的笔记
  const noteIds = await findNotes('deck:ClipLingo*');
  if (noteIds.length === 0) return [];

  // 分批查询（AnkiConnect 单次最多处理 100 条）
  const words: string[] = [];
  const batchSize = 100;
  for (let i = 0; i < noteIds.length; i += batchSize) {
    const batch = noteIds.slice(i, i + batchSize);
    const infos = await notesInfo(batch);
    for (const info of infos) {
      const word = info.fields?.Word?.value?.trim();
      if (word) words.push(word.toLowerCase());
    }
  }

  // 去重
  return [...new Set(words)];
}
