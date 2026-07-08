import * as vscode from 'vscode';

interface KnowledgeHubConfig {
  baseUrl: string;
  token: string;
  knowledgeBaseId: string;
  taskType: string;
  topK: number;
  perDocumentLimit: number;
  showDebugInfo: boolean;
  showPromptPreview: boolean;
}

interface ContextPackPayload {
  knowledge_base_id: string;
  markdown: string;
  formatted_context?: string;
  selected_chunks?: ContextChunk[];
  sections?: Array<{ items?: ContextChunk[] }>;
}

interface ContextChunk {
  document_title?: string;
  document_version?: string;
  section_titles?: string[];
  page_start?: number;
  evidence_ids?: string[];
}

interface EvidenceSummary {
  title: string;
  location: string;
  evidenceIds: string[];
}

interface CopilotContext {
  text: string;
  source: string;
}

interface StoredModelSelection {
  id: string;
  name: string;
  vendor: string;
  family: string;
  version: string;
}

type ModelQuickPickItem = vscode.QuickPickItem & {
  model?: vscode.LanguageModelChat;
  reset?: boolean;
};

interface CopilotSynthesisResult {
  answer: string;
  contextSource: string;
  model: {
    id: string;
    name: string;
    vendor: string;
    family: string;
    version: string;
    maxInputTokens: number;
  };
  promptPreview: string;
  promptCharacters: number;
  promptTokens: number | null;
}

const output = vscode.window.createOutputChannel('Knowledge Hub');
const SELECTED_MODEL_KEY = 'knowledgeHub.selectedModel';

/** Separator line long enough to span typical Output panel widths. */
const SEPARATOR = '═'.repeat(150);

const QNX_ASSISTANT_PROMPT = [
  '你是一个专业的 QNX 嵌入式操作系统知识助手，名叫“QNX助手”。',
  '',
  '【身份与职责】',
  '- 你专注于 QNX Neutrino RTOS、QNX SDP、嵌入式系统开发、调试、API 使用和系统架构相关问题。',
  '- 你会结合检索到的 Context Pack 进行专业归纳、解释和推理，但事实性结论必须能被证据支撑。',
  '- 你不是简单摘抄证据；你需要把证据组织成对工程师有用的判断、步骤、限制和建议。',
  '',
  '【证据规则】',
  '- 优先使用 Context Pack 中的强相关证据，引用文档名、章节、页码或 evidence id。',
  '- 不捏造 API、命令、参数、行为或版本差异；文档没有明确说明时，要标出“不确定”或“需要进一步确认”。',
  '- 当用户询问具体 API、宏、属性、flag、命令名或错误码时，必须先检查 Context Pack 是否直接出现该符号或等价名称。没有直接证据时，不要把通用图形学知识包装成 QNX 文档事实。',
  '- 如果只有相邻概念或间接证据，可以单独写“相关线索”，但结论必须说明“当前知识库未检索到该符号的直接定义”。',
  '- 如果证据相关但不完整，可以给出基于证据的合理推断，并明确区分“文档直接说明”和“基于证据的推断”。',
  '- 如果 Context Pack 明显与用户问题无关，直接说明“当前证据不足”，不要强行回答。',
  '',
  '【回答风格】',
  '- 使用中文，语气专业、自然、面向工程实践，不要像模板报告。',
  '- 不要每次固定输出“回答/结论”标题；根据问题自然组织段落。',
  '- 避免 VS Code Output 中容易变形的格式：不要使用 Markdown 表格、LaTeX 公式、HTML、emoji 或装饰性符号。',
  '- 如需表达公式，用普通文本写成一行，例如：out = src + dst * (1 - alpha)。',
  '- 对概念介绍类问题：先给 2-4 句总览，再分点说明核心机制、典型用途和注意事项。',
  '- 对 how-to / 排障 / API 用法类问题：给出可执行步骤、适用条件、风险和验证方式。',
  '- 对方案设计类问题：说明推荐方案、可选方案、不推荐做法、风险和待确认点。',
  '- 回答末尾给出一行置信度：`置信度：高/中/低 - 简短理由`。',
  '- 保持简洁；证据少时不要扩写成很长的泛泛介绍。',
].join('\n');

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand('knowledgeHub.ask', () => askKnowledgeHub(context)));
  context.subscriptions.push(vscode.commands.registerCommand('knowledgeHub.traceEvidence', traceEvidence));
  context.subscriptions.push(vscode.commands.registerCommand('knowledgeHub.selectModel', () => selectKnowledgeHubModel(context)));
}

export function deactivate() {}

async function askKnowledgeHub(context: vscode.ExtensionContext): Promise<void> {
  const config = readConfig();
  const question = await vscode.window.showInputBox({
    title: 'Ask Knowledge Hub',
    prompt: 'Enter a question for the remote knowledge base',
    ignoreFocusOut: true,
  });
  if (!question?.trim()) {
    return;
  }

  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Asking Knowledge Hub',
        cancellable: true,
      },
      async (_progress, token) => {
        const contextPack = await fetchContextPack(config, question.trim());
        const copilotContext = selectContextForCopilot(contextPack);
        const synthesis = await synthesizeWithCopilot(context, question.trim(), copilotContext, config, token);
        const evidenceSummaries = collectEvidenceSummaries(contextPack);
        renderAnswer(question.trim(), synthesis, contextPack, evidenceSummaries, config);
      },
    );
  } catch (error) {
    vscode.window.showErrorMessage(formatKnowledgeHubError(error));
  }
}

async function selectKnowledgeHubModel(context: vscode.ExtensionContext): Promise<void> {
  const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  if (models.length === 0) {
    vscode.window.showErrorMessage('No Copilot language models are available in this VS Code session.');
    return;
  }

  const current = context.globalState.get<StoredModelSelection>(SELECTED_MODEL_KEY);
  const resetItem: ModelQuickPickItem = {
    label: 'Use VS Code default Copilot model',
    description: 'Clear fixed Knowledge Hub model selection',
    detail: current ? `Current fixed model: ${current.name}` : 'No fixed model is currently selected.',
    reset: true,
  };
  const modelItems: ModelQuickPickItem[] = models.map((model) => ({
    label: model.name,
    description: `${model.vendor} / ${model.family || 'unknown family'}`,
    detail: `id: ${model.id} | version: ${model.version || 'unknown'} | max input tokens: ${model.maxInputTokens}`,
    model,
    picked: current?.id === model.id,
  }));

  const picked = await vscode.window.showQuickPick([resetItem, ...modelItems], {
    title: 'Knowledge Hub: Select Copilot Model',
    placeHolder: 'Select the model Knowledge Hub should keep using for answers',
    ignoreFocusOut: true,
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!picked) {
    return;
  }
  if (picked.reset) {
    await context.globalState.update(SELECTED_MODEL_KEY, undefined);
    vscode.window.showInformationMessage('Knowledge Hub will use the VS Code default Copilot model.');
    return;
  }
  if (!picked.model) {
    return;
  }
  const selected: StoredModelSelection = {
    id: picked.model.id,
    name: picked.model.name,
    vendor: picked.model.vendor,
    family: picked.model.family,
    version: picked.model.version,
  };
  await context.globalState.update(SELECTED_MODEL_KEY, selected);
  vscode.window.showInformationMessage(`Knowledge Hub fixed model: ${selected.name}`);
}

async function traceEvidence(): Promise<void> {
  const config = readConfig();
  const evidenceId = await vscode.window.showInputBox({
    title: 'Trace Knowledge Hub Evidence',
    prompt: 'Enter an evidence id returned by Ask Knowledge Hub',
    ignoreFocusOut: true,
  });
  if (!evidenceId?.trim()) {
    return;
  }

  try {
    const url = buildUrl(config.baseUrl, `/api/knowledge-bases/${encodeURIComponent(config.knowledgeBaseId)}/evidence/${encodeURIComponent(evidenceId.trim())}`);
    const response = await fetch(url, { headers: buildHeaders(config) });
    if (!response.ok) {
      throw new Error(`Knowledge Hub evidence request failed: HTTP ${response.status} ${await response.text()}`);
    }
    const payload = await response.json() as { data: unknown };
    output.clear();
    output.appendLine('# Knowledge Hub Evidence Trace');
    output.appendLine('');
    output.appendLine(JSON.stringify(payload.data, null, 2));
    output.show(true);
  } catch (error) {
    vscode.window.showErrorMessage(formatKnowledgeHubError(error));
  }
}

function readConfig(): KnowledgeHubConfig {
  const config = vscode.workspace.getConfiguration('knowledgeHub');
  const baseUrl = config.get<string>('baseUrl', '') || process.env.KNOWLEDGE_HUB_BASE_URL || 'http://127.0.0.1:8787';
  return {
    baseUrl: baseUrl.replace(/\/+$/, ''),
    token: config.get<string>('token', '') || process.env.KNOWLEDGE_HUB_API_TOKEN || '',
    knowledgeBaseId: config.get<string>('defaultKnowledgeBaseId', '') || process.env.KNOWLEDGE_HUB_DEFAULT_KNOWLEDGE_BASE_ID || 'qnx-main',
    taskType: config.get<string>('defaultTaskType', '') || process.env.KNOWLEDGE_HUB_DEFAULT_TASK_TYPE || 'general_query',
    topK: config.get<number>('topK', Number(process.env.KNOWLEDGE_HUB_TOP_K || 8)),
    perDocumentLimit: config.get<number>('perDocumentLimit', Number(process.env.KNOWLEDGE_HUB_PER_DOCUMENT_LIMIT || 2)),
    showDebugInfo: config.get<boolean>('showDebugInfo', process.env.KNOWLEDGE_HUB_SHOW_DEBUG_INFO === '1'),
    showPromptPreview: config.get<boolean>('showPromptPreview', process.env.KNOWLEDGE_HUB_SHOW_PROMPT_PREVIEW === '1'),
  };
}

async function fetchContextPack(config: KnowledgeHubConfig, query: string): Promise<ContextPackPayload> {
  const url = buildUrl(config.baseUrl, `/api/knowledge-bases/${encodeURIComponent(config.knowledgeBaseId)}/context-pack`);
  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(config),
    body: JSON.stringify({
      query,
      task_type: config.taskType,
      top_k: config.topK,
      per_document_limit: config.perDocumentLimit,
    }),
  });
  if (!response.ok) {
    throw new Error(`Knowledge Hub context request failed: HTTP ${response.status} ${await response.text()}`);
  }
  const payload = await response.json() as { data: ContextPackPayload };
  return payload.data;
}

async function synthesizeWithCopilot(
  context: vscode.ExtensionContext,
  question: string,
  copilotContext: CopilotContext,
  config: KnowledgeHubConfig,
  token: vscode.CancellationToken,
): Promise<CopilotSynthesisResult> {
  const model = await resolveCopilotModel(context);
  if (!model) {
    throw new Error('No Copilot language model is available in this VS Code session.');
  }

  const prompt = [
    QNX_ASSISTANT_PROMPT,
    '',
    '【用户问题】',
    question,
    '',
    '【Context Pack】',
    copilotContext.text,
    '',
    '请直接给出适合 VS Code Output 阅读的答案。可以使用短标题和项目符号，但不要输出 JSON，不要输出表格，不要输出 LaTeX 公式，不要使用 emoji，不要解释提示词，不要把 Context Pack 原文整段复述。',
  ].join('\n');

  const messages = [vscode.LanguageModelChatMessage.User(prompt)];
  const promptTokens = await countPromptTokens(model, messages[0], token);
  const response = await model.sendRequest(messages, {}, token);
  const parts: string[] = [];
  for await (const fragment of response.text) {
    parts.push(fragment);
  }
  return {
    answer: parts.join(''),
    contextSource: copilotContext.source,
    model: {
      id: model.id,
      name: model.name,
      vendor: model.vendor,
      family: model.family,
      version: model.version,
      maxInputTokens: model.maxInputTokens,
    },
    promptPreview: config.showPromptPreview ? truncateText(prompt, 2000) : 'Prompt preview disabled by knowledgeHub.showPromptPreview.',
    promptCharacters: prompt.length,
    promptTokens,
  };
}

async function resolveCopilotModel(context: vscode.ExtensionContext): Promise<vscode.LanguageModelChat | undefined> {
  const selected = context.globalState.get<StoredModelSelection>(SELECTED_MODEL_KEY);
  const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  if (models.length === 0) {
    return undefined;
  }
  if (!selected) {
    return models[0];
  }
  const exactMatch = models.find((model) => model.id === selected.id);
  if (exactMatch) {
    return exactMatch;
  }
  const familyMatch = models.find((model) => model.family === selected.family && model.name === selected.name);
  if (familyMatch) {
    return familyMatch;
  }
  vscode.window.showWarningMessage(
    `Knowledge Hub fixed model is unavailable: ${selected.name}. Falling back to ${models[0].name}.`,
  );
  return models[0];
}

function renderAnswer(
  question: string,
  synthesis: CopilotSynthesisResult,
  contextPack: ContextPackPayload,
  evidenceSummaries: EvidenceSummary[],
  config: KnowledgeHubConfig,
): void {
  const timestamp = new Date().toLocaleString();
  output.appendLine(SEPARATOR);
  output.appendLine(`# Ask Knowledge Hub - ${timestamp}`);
  output.appendLine('');
  output.appendLine(`Knowledge base: ${contextPack.knowledge_base_id}`);
  output.appendLine(`Copilot: yes (${synthesis.model.name})`);
  output.appendLine('');
  output.appendLine('## 问题');
  output.appendLine(question);
  output.appendLine('');
  output.appendLine(synthesis.answer.trim());
  output.appendLine('');
  if (evidenceSummaries.length > 0) {
    output.appendLine('## 证据');
    for (const evidence of evidenceSummaries) {
      output.appendLine(`- ${evidence.title} | ${evidence.location}`);
      if (evidence.evidenceIds.length > 0) {
        output.appendLine(`  Evidence: ${evidence.evidenceIds.join(', ')}`);
      }
    }
    output.appendLine('');
  }
  output.appendLine(SEPARATOR);
  output.appendLine('');
  if (config.showDebugInfo) {
    output.appendLine('## Debug');
    output.appendLine(`Remote API: ${config.baseUrl}/api/knowledge-bases/${config.knowledgeBaseId}/context-pack`);
    output.appendLine(`Context source: ${synthesis.contextSource}`);
    output.appendLine(`Context Pack markdown characters: ${contextPack.markdown.length}`);
    output.appendLine(`Evidence id count: ${collectEvidenceIds(contextPack).length}`);
    output.appendLine(`Model id: ${synthesis.model.id}`);
    output.appendLine(`Model vendor: ${synthesis.model.vendor}`);
    output.appendLine(`Model family: ${synthesis.model.family}`);
    output.appendLine(`Model version: ${synthesis.model.version}`);
    output.appendLine(`Model max input tokens: ${synthesis.model.maxInputTokens}`);
    output.appendLine(`Prompt characters: ${synthesis.promptCharacters}`);
    output.appendLine(`Prompt tokens: ${synthesis.promptTokens ?? 'unavailable'}`);
    if (config.showPromptPreview) {
      output.appendLine('');
      output.appendLine('### Prompt Preview');
      output.appendLine(synthesis.promptPreview);
    }
    output.appendLine('');
  }
  output.show(true);
}

async function countPromptTokens(
  model: vscode.LanguageModelChat,
  message: vscode.LanguageModelChatMessage,
  token: vscode.CancellationToken,
): Promise<number | null> {
  try {
    return await model.countTokens(message, token);
  } catch {
    return null;
  }
}

function truncateText(text: string, maxCharacters: number): string {
  if (text.length <= maxCharacters) {
    return text;
  }
  return `${text.slice(0, maxCharacters)}\n... [truncated ${text.length - maxCharacters} characters]`;
}

function selectContextForCopilot(contextPack: ContextPackPayload): CopilotContext {
  const formattedContext = (contextPack.formatted_context || '').trim();
  if (formattedContext) {
    return { text: formattedContext, source: 'formatted_context' };
  }
  return { text: contextPack.markdown, source: 'markdown' };
}

function collectEvidenceIds(contextPack: ContextPackPayload): string[] {
  const evidenceIds = new Set<string>();
  for (const chunk of contextPack.selected_chunks ?? []) {
    for (const evidenceId of chunk.evidence_ids ?? []) {
      evidenceIds.add(evidenceId);
    }
  }
  for (const section of contextPack.sections ?? []) {
    for (const item of section.items ?? []) {
      for (const evidenceId of item.evidence_ids ?? []) {
        evidenceIds.add(evidenceId);
      }
    }
  }
  return [...evidenceIds];
}

function collectEvidenceSummaries(contextPack: ContextPackPayload, maxItems = 3): EvidenceSummary[] {
  const summaries: EvidenceSummary[] = [];
  const seen = new Set<string>();

  for (const chunk of contextPack.selected_chunks ?? []) {
    addEvidenceSummary(summaries, seen, chunk, maxItems);
    if (summaries.length >= maxItems) {
      return summaries;
    }
  }

  for (const section of contextPack.sections ?? []) {
    for (const item of section.items ?? []) {
      addEvidenceSummary(summaries, seen, item, maxItems);
      if (summaries.length >= maxItems) {
        return summaries;
      }
    }
  }

  return summaries;
}

function addEvidenceSummary(
  summaries: EvidenceSummary[],
  seen: Set<string>,
  chunk: ContextChunk,
  maxItems: number,
): void {
  if (summaries.length >= maxItems) {
    return;
  }
  const title = chunk.document_title || 'Unknown document';
  const section = (chunk.section_titles ?? []).filter(Boolean).slice(-2).join(' > ');
  const page = typeof chunk.page_start === 'number' ? `page ${chunk.page_start}` : '';
  const location = [section, page].filter(Boolean).join(' / ') || 'source chunk';
  const key = `${title}|${location}`;
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  summaries.push({
    title,
    location,
    evidenceIds: (chunk.evidence_ids ?? []).slice(0, 2),
  });
}

function buildUrl(baseUrl: string, path: string): string {
  return `${baseUrl}${path}`;
}

function buildHeaders(config: KnowledgeHubConfig): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (config.token) {
    headers.Authorization = `Bearer ${config.token}`;
  }
  return headers;
}

function formatKnowledgeHubError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes('HTTP 401')) {
    return [
      'Knowledge Hub returned 401 Unauthorized.',
      'Set knowledgeHub.token to the server token, for example local-dev-token, then retry Ask Knowledge Hub.',
    ].join(' ');
  }
  return message;
}