// Isolated demonstration. Never used as a fallback when the API fails.

const TOPICS = [
  "Дроби",
  "Линейные уравнения",
  "Квадратные уравнения и дискриминант",
  "Геометрия",
];

function cell(title, status, percent) {
  return { title, status, correct_percent: percent, stalled: false };
}

export function previewRole(value, entry) {
  if (value === "teacher") return "teacher";
  if (value === "student") return "student";
  if (value === "1") return entry === "teacher" ? "teacher" : "student";
  return null;
}

export function sampleLesson() {
  return {
    ok: true,
    mode: "training",
    step: "explain",
    topic: "Дроби",
    explanation:
      "Дробь показывает часть целого: числитель — сколько частей взяли, знаменатель — на сколько равных частей разделили.",
    example: "1/2 + 1/4. Общий знаменатель 4, поэтому 1/2 = 2/4. 2/4 + 1/4 = 3/4.",
    task: "Сложи 1/3 и 1/6. Напиши результат дробью.",
    feedback: null,
    correct: null,
    given: null,
    actions: [
      { action: "more_example", label: "Ещё пример", topic: null },
      { action: "to_practice", label: "К практике", topic: null },
    ],
    notice: "Демонстрационный разбор. Сервер не вызывался, ответ не проверяется.",
    status_line: null,
    awaiting_answer: true,
    photo_received: false,
    photo_note: null,
    preview: true,
  };
}

export function studentPreview() {
  return {
    displayName: "Алексей",
    progress: {
      display_name: "Алексей",
      class_title: "8Б",
      streak_days: 2,
      completed_tasks: 6,
      next_step: "Повторить тему «Геометрия»",
      next_topic: "Геометрия",
      topics: [
        { title: "Дроби", status: "needs_practice", correct_percent: 67 },
        { title: "Линейные уравнения", status: "mastered", correct_percent: 100 },
        { title: "Квадратные уравнения и дискриминант", status: "needs_practice", correct_percent: 50 },
        { title: "Геометрия", status: "repeat", correct_percent: 25 },
      ],
    },
    history: {
      sessions: [
        { mode: "training", topic: "Геометрия", created_at: "2026-10-28T10:00:00+10:00", answered: 2, correct_count: 0 },
        { mode: "training", topic: "Дроби", created_at: "2026-10-27T10:00:00+10:00", answered: 2, correct_count: 1 },
        { mode: "training", topic: "Линейные уравнения", created_at: "2026-10-26T10:00:00+10:00", answered: 2, correct_count: 2 },
      ],
    },
    openLesson: { step: "idle" },
  };
}

export function teacherPreview() {
  const names = ["Алексей", "Аня", "Кирилл", "Ольга"];
  const grid = {
    Алексей: [
      cell(TOPICS[0], "needs_practice", 67),
      cell(TOPICS[1], "mastered", 100),
      cell(TOPICS[2], "repeat", 30),
      cell(TOPICS[3], null, null),
    ],
    Аня: [
      cell(TOPICS[0], "mastered", 100),
      cell(TOPICS[1], "mastered", 100),
      cell(TOPICS[2], "needs_practice", 70),
      cell(TOPICS[3], "needs_practice", 55),
    ],
    Кирилл: [
      cell(TOPICS[0], null, null),
      cell(TOPICS[1], null, null),
      cell(TOPICS[2], null, null),
      cell(TOPICS[3], "repeat", 20),
    ],
    Ольга: [
      cell(TOPICS[0], null, null),
      cell(TOPICS[1], "needs_practice", 80),
      cell(TOPICS[2], null, null),
      cell(TOPICS[3], null, null),
    ],
  };
  return {
    displayName: "Марина Сергеевна",
    report: {
      class_title: "8Б",
      topics: TOPICS.map((title) => ({ title })),
      students: names.map((name) => ({ display_name: name, topics: grid[name] })),
      priorities: [
        "Квадратные уравнения и дискриминант: повторить — Алексей",
        "Геометрия: повторить — Кирилл",
      ],
      frequent_mistakes: "Чаще всего ошибки в теме «Квадратные уравнения и дискриминант».",
      stalled: ["Кирилл — Геометрия, последняя попытка 01.10"],
      subject_title: "Математика",
      classes: [{ id: 1, title: "8Б", subjects: [{ id: 1, title: "Математика" }] }],
      can_manage_school: true,
      claims_reviewer: "Марина Сергеевна",
      active_students: 4,
      teacher_count: 1,
      join_code: "8BDEMO",
      pending_claims: [
        {
          user_id: 8,
          display_name: "Егор",
          class_title: "8Б",
          created_at: "2026-11-03T08:40:00",
          status: "pending",
        },
      ],
    },
    assignments: {
      items: [],
      delivery: "sample",
      detail: "Демонстрационный список. Это не работы класса и не ответ сервера.",
    },
  };
}
