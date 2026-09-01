import fs from "node:fs/promises";
import { pathToFileURL } from "node:url";


function valueAfter(flag) {
  const index = process.argv.indexOf(flag);
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`Missing ${flag}`);
  }
  return process.argv[index + 1];
}


const input = valueAfter("--input");
const confirmationPath = valueAfter("--confirmation");
const output = valueAfter("--output");
const artifactToolPath = valueAfter("--artifact-tool");
const { FileBlob, PresentationFile } = await import(pathToFileURL(artifactToolPath).href);
const confirmation = JSON.parse(await fs.readFile(confirmationPath, "utf8"));
if (confirmation.status !== "CONFIRMED" || !Array.isArray(confirmation.members) || confirmation.members.length !== 3) {
  throw new Error("TEAM_CONFIRMATION.json must contain exactly three confirmed members");
}

const presentation = await PresentationFile.importPptx(await FileBlob.load(input));

function setText(id, value) {
  const target = presentation.resolve(id);
  if (!target?.text) throw new Error(`Missing text target ${id}`);
  target.text = value;
}

setText("sh/wbydknq1", "成员背景与分工");
setText(
  "sh/idgvmx8r",
  "以下姓名、背景、角色与职责已由三名报名成员确认内容准确、同意用于比赛材料并确认初赛成员锁定。项目全程Clean-room开发。",
);

const expectedMembers = [
  {
    name: "顾梓洋",
    role: "统筹 · 工程化交付",
    responsibilities: "Skill/Schema、状态与证据管理、工程化/许可证、Demo与提交材料",
  },
  {
    name: "刘志豪",
    role: "技术架构 · 工具链",
    responsibilities: "总体技术架构；AgentTeams编排、HTTP Tool Gateway与3D确定性核心",
  },
  {
    name: "王峥睿",
    role: "评测 · 实验分析",
    responsibilities: "自建样本、缺陷注入、Regression Verifier、指标与实验分析",
  },
];
confirmation.members.forEach((member, index) => {
  const expected = expectedMembers[index];
  if (
    member.name !== expected.name ||
    member.role !== expected.role ||
    member.responsibilities !== expected.responsibilities
  ) {
    throw new Error(
      `Member ${index + 1} differs from the reviewed deck. Update and review the V3 deck before finalizing.`,
    );
  }
});

setText("sh/n6pkrelc", "初赛代码暂不公开；三名成员信息与分工已确认");
setText("sh/8ry10jmx", "✓ 已确认");
setText("sh/50behwr2", "PPT V3、500字简介、Demo截图与提交预填");
setText("sh/4z2d8rah", "✓ 已完成");
setText(
  "sh/ehkzepsn",
  "7个核心Skill：Profile、包审计、Mesh验证、修复计划、安全修复、纹理安全缩放、独立回归验证",
);

const notes = presentation.resolve("nt/6lsnupw7");
if (!notes?.setText) throw new Error("Missing team slide notes target");
notes.setText(
  "[Sources]\n- TEAM_CONFIRMATION.json（三名报名成员确认）\n- SceneGuard 正式材料/08_团队介绍素材表.md\n- 本页未使用外部图片资产",
);

const finalPptx = await PresentationFile.exportPptx(presentation);
await finalPptx.save(output);
console.log(output);
