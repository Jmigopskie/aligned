// Alan's opening line for each part in the Guided chat: a short, built-in
// explanation of what the part is and how to write it. Written here, not asked
// of the AI, so opening a part costs nothing. Lines starting "- " are shown as
// a bulleted list. Matched on the part's label (and key), first rule wins, so
// the specific rules (content standard) come before the general ones (content).

const PART_GUIDES = [
  [/reflection|remarks|no\.? of learners|teaching strategies worked|difficulties did i encounter|innovation/,
    "This part is filled in after you teach the lesson: what happened, how many learners mastered it, and what you would change. Leave it until then."],
  [/content standard/,
    "The content standard says what learners should understand. Copy the statement for this lesson from your selected Budget of Work or Curriculum Guide, word for word."],
  [/performance standard/,
    "The performance standard says what learners can do or make with what they learned. Copy it word for word from your Budget of Work or Curriculum Guide, from the same row as your content standard."],
  [/competenc|melc/,
    "The learning competency is the one skill this lesson targets. Copy it word for word from your Budget of Work or Curriculum Guide, for this lesson's topic. Objectives go in their own part."],
  [/objective/,
    "Learning objectives say what learners will be able to do by the end of the lesson. Write three, one per line, each starting with a measurable verb:\n- one for knowing (identify, explain, compare)\n- one for feeling or valuing (value, show, appreciate)\n- one for doing (perform, create, demonstrate)"],
  [/reference|resource|material|teacher'?s guide|textbook|lr portal/,
    "List what you will teach from: your Budget of Work or Curriculum Guide, textbook pages, and online sources. Write online sources in APA format with a link that opens."],
  [/routine|preliminar/,
    "Routine activities open the class. The usual routine is:\n- Greetings\n- Prayer\n- Checking of attendance\n- Classroom rules (listen while others speak, raise your hand to talk, keep the room clean, respect everyone)"],
  [/assignment|additional activit|agreement|extended|enrichment|remediation|homework/,
    "The assignment lets learners practise or prepare at home. Keep it short and tied to today's competency, or to the next lesson."],
  [/review|recap|previous lesson|drill/,
    "The review connects yesterday's lesson to today's. A few quick questions about the last topic are enough."],
  [/motivation|purpose|hook|engage|elicit/,
    "The motivation catches interest and shows why today's topic matters: a picture, a short game, a question or a real-life situation, done in a few minutes."],
  [/mastery|practice/,
    "Developing mastery gives learners guided practice: a short activity they do themselves, so you can check they understood before the final evaluation."],
  [/application|daily living|elaborat/,
    "The application has learners use the lesson in a real-life situation, at home, in school or in the community."],
  [/generaliz|abstraction|valuing/,
    "The generalization is where learners sum up the lesson in their own words: the key idea and why it matters. Guide them with one or two questions."],
  [/evaluat|assessment|quiz|test/,
    "The evaluation checks whether the objectives were met: a short quiz or task that measures each objective, with its answer key or rubric."],
  [/discussion|presentation|presenting|lesson proper|procedure|\bflow\b|explain|explore|instruction|analysis|activit/,
    "This is the heart of the lesson: how you teach today's topic step by step, with examples and questions for the class."],
  [/content|subject matter|topic/,
    "The content is the topic of the lesson in a few words, as your Budget of Work or Curriculum Guide names it."],
];

function partGuide(field) {
  const name = `${field.label || ""} ${String(field.field_key || "").replace(/_/g, " ")}`.toLowerCase();
  const rule = PART_GUIDES.find(([pattern]) => pattern.test(name));
  if (rule) return rule[1];
  // Nothing matched: the format's own hint for the part, else a general line.
  const hint = String(field.ai_hint || "").split(/(?<=[.!?])\s/)[0].trim();
  return hint
    ? `${field.label}: ${hint}`
    : `${field.label}: write it for this lesson's topic, in your own words. Ask me if you're unsure what goes here.`;
}
