import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const runnerScript = path.join(__dirname, 'scripts', 'runner.py');

/**
 * 动态探测当前活跃的项目工作目录
 */
function resolveProjectRoot(customRoot, ctx) {
  if (customRoot && fs.existsSync(customRoot)) {
    return path.resolve(customRoot);
  }
  try {
    const registry = ctx?.get?.('workspaceRegistry') || ctx?.workspaceRegistry;
    if (registry && typeof registry.list === 'function') {
      const list = registry.list();
      if (list && list.length > 0 && list[0]?.path) {
        return path.resolve(list[0].path);
      }
    }
  } catch (_) {}
  return process.cwd();
}

/**
 * 执行 Python 桥接器辅助函数，锁定 UTF-8 编码与长超时
 */
function runPython(args = [], cwd = process.cwd(), timeoutMs = 300000, pythonBin = 'python') {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    };

    execFile(
      pythonBin,
      [runnerScript, ...args],
      { cwd, env, timeout: timeoutMs, maxBuffer: 25 * 1024 * 1024, encoding: 'utf-8' },
      (err, stdout, stderr) => {
        resolve({
          success: !err,
          code: err ? (typeof err.code === 'number' ? err.code : 1) : 0,
          stdout: stdout ? stdout.trim() : '',
          stderr: stderr ? stderr.trim() : '',
          error: err ? String(err.message || err) : undefined,
        });
      }
    );
  });
}

function normalizeRunnerResponse(res) {
  const numericCode = typeof res.code === 'number' ? res.code : (res.success ? 0 : 1);

  if (!res.success && !res.stdout) {
    const out = {
      success: false,
      code: numericCode,
      error: String(res.error || res.stderr || 'Python runner execution failed'),
    };
    if (res.stderr) {
      out.stderr = res.stderr;
    }
    return out;
  }

  try {
    const parsed = JSON.parse(res.stdout);
    const out = {
      ...parsed,
      code: typeof parsed?.code === 'number' ? parsed.code : numericCode,
    };
    if (res.stderr) {
      out.stderr = res.stderr;
    }
    if (out.error === null || out.error === undefined) {
      delete out.error;
    } else if (typeof out.error !== 'string') {
      out.error = String(out.error);
    }
    return out;
  } catch (parseErr) {
    return {
      success: false,
      code: numericCode !== 0 ? numericCode : 1,
      raw_stdout: res.stdout,
      raw_stderr: res.stderr,
      error: `JSON 解析失败: ${parseErr.message}`,
    };
  }
}

export const inject = ['tools'];

export function apply(ctx, config = {}) {
  const pythonBin = config.pythonPath || 'python';

  // =========================================================================
  // 1. 注册核心驱动工具: langgraph_courseware_pipeline
  // =========================================================================
  ctx.tools.register({
    name: 'langgraph_courseware_pipeline',
    description: 'LangGraph 自动化自学教材教研流水线驱动工具。支持启动流水线(run)、断点恢复(resume)、检查点与状态查询(status)、导出计算图Mermaid拓扑(visualize)、运行全量单测(test)。',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['run', 'resume', 'status', 'visualize', 'test'],
          description: '流水线操作动作：run(启动) | resume(断点恢复) | status(查询状态) | visualize(导出Mermaid计算图) | test(全量测试)',
        },
        raw_files: {
          type: 'array',
          items: { type: 'string' },
          description: '原始课本/讲义原材料文件路径列表（Markdown 或 PDF），run 时使用',
        },
        discipline: {
          type: 'string',
          enum: ['math', 'physics'],
          description: '学科领域配置：math(数学，默认) | physics(物理)',
        },
        output_dir: {
          type: 'string',
          description: '最小可交付包输出目录（缺省时自动在输入文件所在目录下建立 <string>_uncle 子文件夹，其中 string 为输入文件名）',
        },
        checkpoint_db: {
          type: 'string',
          description: 'SQLite 检查点数据库路径（默认为 pipeline_state.db）',
        },
        thread_id: {
          type: 'string',
          description: '会话线程 ID（默认为 session_01）',
        },
        resume: {
          type: 'boolean',
          description: '是否断点恢复模式',
        },
        max_retry: {
          type: 'number',
          description: '门禁最大重试次数（默认为 3）',
        },
        project_root: {
          type: 'string',
          description: '项目根目录路径（缺省时自动探测工作区）',
        },
      },
      required: ['action'],
    },
    output: {
      schema: {
        type: 'object',
        properties: {
          success: { type: 'boolean' },
          code: { type: 'number' },
          error: { type: 'string' },
          output: { type: 'string' },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
      }],
    },
    async execute(args) {
      const projRoot = resolveProjectRoot(args.project_root, ctx);
      const action = args.action || 'status';

      const cliArgs = ['--action', action, '--project-root', projRoot];

      if (action === 'run' || action === 'resume') {
        const isResume = action === 'resume' || Boolean(args.resume);
        const rawFiles = Array.isArray(args.raw_files) ? args.raw_files : [];
        if (!isResume && rawFiles.length === 0) {
          return {
            success: false,
            code: 1,
            error: '启动流水线必须提供 raw_files（至少一个输入原材料文件路径）。',
          };
        }
        if (rawFiles.length > 0) {
          cliArgs.push('--input', ...rawFiles);
        }
        if (args.discipline) {
          cliArgs.push('--discipline', args.discipline);
        }
        if (args.output_dir) {
          cliArgs.push('--output', args.output_dir);
        }
        if (args.checkpoint_db) {
          cliArgs.push('--checkpoint-db', args.checkpoint_db);
        }
        if (args.thread_id) {
          cliArgs.push('--thread-id', args.thread_id);
        }
        if (isResume) {
          cliArgs.push('--resume');
        }
        if (args.max_retry) {
          cliArgs.push('--max-retry', String(args.max_retry));
        }
      } else if (action === 'status') {
        if (args.checkpoint_db) {
          cliArgs.push('--checkpoint-db', args.checkpoint_db);
        }
        if (args.thread_id) {
          cliArgs.push('--thread-id', args.thread_id);
        }
      } else if (action === 'visualize') {
        if (args.max_retry) {
          cliArgs.push('--max-retry', String(args.max_retry));
        }
      }

      const res = await runPython(cliArgs, projRoot, 600000, pythonBin);
      return normalizeRunnerResponse(res);
    },
  });

  // =========================================================================
  // 2. 注册门禁校验工具: langgraph_courseware_gate
  // =========================================================================
  ctx.tools.register({
    name: 'langgraph_courseware_gate',
    description: 'LangGraph 自学教材流水线确定性质量门禁核验工具。支持对当前状态执行全部门禁(all)或单项门禁测试(source_gate, diagnosis_gate, dependency_gate, pedagogy_gate, feedback_gate, student_trial_gate, output_gate, version_gate)。',
    parameters: {
      type: 'object',
      properties: {
        gate: {
          type: 'string',
          enum: [
            'all',
            'source_gate',
            'diagnosis_gate',
            'dependency_gate',
            'pedagogy_gate',
            'feedback_gate',
            'student_trial_gate',
            'output_gate',
            'version_gate',
          ],
          description: '待校验门禁名称，all 表示运行全部 8 个门禁',
        },
        state_file: {
          type: 'string',
          description: '待检查的 GraphState 状态 JSON 文件路径（可选，未提供时使用静态基准测试）',
        },
        project_root: {
          type: 'string',
          description: '项目根目录路径（缺省时自动探测工作区）',
        },
      },
      required: ['gate'],
    },
    output: {
      schema: {
        type: 'object',
        properties: {
          success: { type: 'boolean' },
          code: { type: 'number' },
          error: { type: 'string' },
          output: { type: 'string' },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
      }],
    },
    async execute(args) {
      const projRoot = resolveProjectRoot(args.project_root, ctx);
      const gateName = args.gate || 'all';

      const cliArgs = ['--action', 'gate', '--gate', gateName, '--project-root', projRoot];
      if (args.state_file) {
        cliArgs.push('--state-file', args.state_file);
      }

      const res = await runPython(cliArgs, projRoot, 120000, pythonBin);
      return normalizeRunnerResponse(res);
    },
  });
}
