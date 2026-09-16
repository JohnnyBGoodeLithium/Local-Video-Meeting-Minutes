/* Reading structures, not new factual sources. Keep prompts visible and editable. */
const grounded = {
  zh: "只使用已有事实和证据；保留原有依据、来源与不确定性。合并要点时保留全部相关依据。缺少内容的栏目直接省略，不填‘暂无’，不补造人物、数字、结论、操作步骤或链接。区分讲者观点、实际演示、假设案例与正式决定；建议、练习和学习邀请不写成正式待办。每条正文或表格数据行附原有证据标记。用中文 Markdown 输出，标题自然简洁。",
  en: "Use only existing facts and evidence. Preserve source markers and uncertainty, including all relevant markers when merging points. Omit unsupported sections; do not invent people, numbers, conclusions, steps or links. Distinguish speaker opinions, observed demonstrations, hypothetical examples and actual decisions. Advice, exercises and invitations to learn are not assigned actions. Attach original evidence markers to each body item or table data row. Write clear English Markdown.",
};

export const MINUTES_TEMPLATES = [
  {
    id: "training",
    zh: { name: "知识分享／培训", description: "梳理概念、方法、演示和学习路径，适合内部分享、培训与课程录屏。", prompt: `请把这份资料整理成适合课后复习的学习笔记，面向未参加分享但需要理解和实践的读者。不要套用决策会议的结构。
按以下顺序组织有依据的内容：
1. 学习导览：面向谁、解决什么问题、3—5 个学习要点。
2. 核心概念与框架：解释定义、关系和差异；适合比较的内容可用表格，保留原术语，不擅自纠正专业名词。
3. 方法与流程：按讲解顺序列出前提、输入、步骤、输出和需要人工核验的环节。
4. 演示与实践案例：逐个梳理目标、输入、实际展示的步骤、观察到的结果和适用条件；明确区分‘讲者声称能做到’与‘现场已经演示’，不补写未展示的成功结果。只提到某个样本异常，不代表其他样本成功；结果未交代就不判断。
5. 能力边界与注意事项：整理限制、失败条件、安全或数据注意事项；不要把一般提醒写成已经发生的事故。
6. 互动练习与答疑：将假设题、练习题与真实提问分开；只记录资料里已有的回答，不替讲者作答。
7. 学习路径与后续安排：保留提到的课程、资源与实践建议；只有明确分配的事项才写负责人和期限。
略去开场设备调试和无信息增量的寒暄；演示遇到的问题若影响结果则保留。优先讲清楚可复用的方法，而不是逐句压缩。` },
    en: { name: "Knowledge sharing / training", description: "Concepts, methods, demonstrations and learning paths for talks, training and recorded courses.", prompt: `Create study notes for someone who missed the session and wants to understand and apply its teaching. Do not force a decision-meeting structure.
Organize supported material into:
1. Learning guide: audience, problem addressed and 3–5 takeaways.
2. Concepts and frameworks: definitions, relationships and comparisons; use tables when helpful and preserve original technical terms.
3. Methods and workflows: prerequisites, inputs, explained steps, outputs and human checks.
4. Demonstrations and examples: goal, input, steps actually shown, observed result and conditions. Separate claimed capabilities from demonstrated outcomes; never invent a successful result. One reported failure does not imply other samples succeeded. Do not judge outcomes that were not reported.
5. Limits and precautions: limitations, failure conditions and safety or data guidance; general advice is not an incident report.
6. Exercises and questions: separate hypothetical quizzes from actual participant questions; include only answers present in the evidence.
7. Further learning and next steps: mentioned courses, resources and practice suggestions; add owners and deadlines only for explicitly assigned actions.
Omit opening equipment checks and small talk unless a demo problem affects the outcome. Explain reusable methods instead of compressing every sentence.` },
  },
  {
    id: "executive",
    zh: { name: "管理层摘要", description: "先看重点、影响与需要判断的问题，减少过程叙述。", prompt: "面向时间有限的管理者整理一份简明阅读摘要。先用3—5点概括最重要的信息，再按‘目标与背景、主要发现及影响、明确决定、待判断的问题与风险、已分配的后续行动’组织。保留关键数字、条件与依据；优先解释影响，省略重复过程。若原资料只是分享或讲解，不强行制造决定和任务。未决建议与已批准事项分开。" },
    en: { name: "Executive brief", description: "Priorities, implications and questions that need a decision, with less process detail.", prompt: "Create a concise brief for a busy manager. Start with 3–5 key points, then organize supported material into goals and context, findings and implications, explicit decisions, unresolved questions and risks, and assigned next actions. Preserve key numbers, conditions and evidence. Prioritize implications over repetitive process detail. Do not manufacture decisions or tasks from a talk or presentation. Separate proposals from approved decisions." },
  },
  {
    id: "review",
    zh: { name: "项目评审", description: "按目标、进展、方案、分歧和后续行动组织评审记录。", prompt: "整理成可供项目跟进的评审纪要。按‘评审目标与范围、当前进展与证据、方案与取舍、评审反馈和未决分歧、明确决定、后续行动’组织。按议题归并重复讨论，保留各方案的前提、优缺点及意见归属。决定须与提议分开；仅对已明确分配的任务记录负责人、期限和验收条件，未给出的字段不得推断。不要把功能介绍视为完成验收。" },
    en: { name: "Project review", description: "Goals, progress, alternatives, disagreements and follow-up actions.", prompt: "Create a project review record organized by scope and goals, progress and evidence, options and tradeoffs, feedback and unresolved disagreements, explicit decisions, and follow-up actions. Group repeated discussion by topic. Preserve each option's assumptions, pros, cons and attribution. Separate decisions from proposals. Record owners, dates and acceptance conditions only when explicitly assigned; never infer missing fields. A feature presentation is not acceptance evidence." },
  },
  {
    id: "product",
    zh: { name: "产品讲解／发布会", description: "按产品和主题梳理卖点、参数、演示、可用性及限制。", prompt: "整理成按产品或主题浏览的讲解笔记。先给出内容导览，再逐项整理‘定位与使用场景、主要能力与参数、演示及观察结果、与其他方案的差异、上市或可用性、限制与待确认信息’。将讲者宣传性主张与现场可观察结果分开，参数保留单位、版本、地区、时间等适用条件。不要把不同产品、不同时间段的资料混在同一项下，也不要把画面展示写成会议决定。未提及价格或发布日期时直接省略。" },
    en: { name: "Product talk / launch", description: "Products, specifications, demonstrations, availability and limitations.", prompt: "Create notes organized by product or topic. Start with a content guide, then cover positioning and use cases, capabilities and specifications, demonstrations and observed results, comparisons, availability, and limitations or open questions. Separate promotional claims from observable outcomes. Preserve units, versions, regions, dates and other conditions for specifications. Do not mix evidence from different products or time ranges. A visual presentation is not a meeting decision. Omit prices and launch dates when absent." },
  },
  {
    id: "custom",
    zh: { name: "自定义结构", description: "自行指定读者、章节、详略和输出语言。", prompt: "" },
    en: { name: "Custom structure", description: "Choose your own audience, sections, level of detail and output language.", prompt: "" },
  },
];

export function minutesTemplate(id, english = false) {
  const item = MINUTES_TEMPLATES.find(template => template.id === id);
  if (!item) throw new Error("Unknown minutes template");
  const language = english ? "en" : "zh";
  const copy = item[language];
  return { id, ...copy, prompt: copy.prompt ? `${copy.prompt}\n\n${grounded[language]}` : "" };
}

export function createMinutesTemplateDialog(dialog) {
  const select = dialog.querySelector("select");
  const input = dialog.querySelector("textarea");
  const form = dialog.querySelector("form");
  const generate = dialog.querySelector('[type="submit"]');
  const drafts = new Map();
  let english = false;
  let selected = "training";
  let onGenerate = null;
  const key = () => `${english}:${selected}`;
  const remember = () => drafts.set(key(), input.value);
  const updateValidity = () => { generate.disabled = !input.value.trim() || input.value.length > 8000; };
  const showSelection = () => {
    const template = minutesTemplate(selected, english);
    dialog.querySelector("#minutes-template-description").textContent = template.description;
    input.value = drafts.get(key()) ?? template.prompt;
    updateValidity();
  };
  select.onchange = () => { remember(); selected = select.value; showSelection(); };
  input.oninput = updateValidity;
  dialog.querySelector('[data-template-cancel]').onclick = () => { remember(); dialog.close(); };
  dialog.addEventListener("cancel", remember);
  // Keep Escape inside the native modal; browser supplies focus trapping and restoration.
  dialog.addEventListener("keydown", event => {
    if (event.key === "Escape") event.stopPropagation();
  });
  form.onsubmit = event => {
    event.preventDefault();
    if (!input.value.trim() || input.value.length > 8000) return;
    remember();
    const prompt = input.value.trim();
    dialog.close();
    onGenerate?.(prompt);
  };
  return {
    show(options) {
      if (dialog.open) return;
      english = options.english;
      onGenerate = options.onGenerate;
      select.replaceChildren(...MINUTES_TEMPLATES.map(item => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = minutesTemplate(item.id, english).name;
        return option;
      }));
      select.value = selected;
      const copy = english ? {
        title: "Restructure minutes", preset: "Reading structure", prompt: "Instructions · editable",
        help: "Uses existing facts and evidence. Missing detail requires processing the source again. Review the preview before saving a separate reading view.",
        cancel: "Cancel", generate: "Generate preview",
        placeholder: "Describe your audience, sections and level of detail…",
      } : {
        title: "重组纪要", preset: "阅读结构", prompt: "提示词 · 可编辑",
        help: "基于已有事实与证据整理；缺失细节需重新处理素材。生成后先核对预览，再保存为独立阅读版本。",
        cancel: "取消", generate: "生成预览", placeholder: "描述读者、章节顺序和详略要求…",
      };
      for (const [name, value] of Object.entries(copy)) {
        if (name === "placeholder") input.placeholder = value;
        else dialog.querySelector(`[data-template-copy="${name}"]`).textContent = value;
      }
      showSelection();
      dialog.showModal();
      select.focus();
    },
    reset() {
      if (dialog.open) dialog.close();
      onGenerate = null;
      drafts.clear();
      selected = "training";
      input.value = "";
    },
  };
}
