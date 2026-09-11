import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { DOCKER_BUNDLE_SCRIPT } from "../lib/constructs/python-lambda";

/**
 * The Docker bundling script only runs on a real `cdk deploy` (Jest synths
 * with `aws:cdk:bundling-stacks: []`), so a broken script is invisible until
 * the production deploy. Exercise it here with plain bash against a temp
 * asset directory; pip is skipped by leaving requirements.txt out.
 */
describe("DOCKER_BUNDLE_SCRIPT", () => {
  test("is newline-joined and parses as bash", () => {
    expect(DOCKER_BUNDLE_SCRIPT.split("\n").length).toBeGreaterThan(5);
    const check = spawnSync("bash", ["-n", "-c", DOCKER_BUNDLE_SCRIPT], {
      encoding: "utf8",
    });
    expect(check.stderr).toBe("");
    expect(check.status).toBe(0);
  });

  test("copies handler modules and asset dirs, skips caches and requirements", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "py-bundle-"));
    const input = path.join(root, "asset-input");
    const output = path.join(root, "asset-output");
    fs.mkdirSync(path.join(input, "fonts"), { recursive: true });
    fs.mkdirSync(path.join(input, "brand", "__pycache__"), { recursive: true });
    fs.mkdirSync(path.join(input, "__pycache__"), { recursive: true });
    fs.mkdirSync(path.join(input, ".pytest_cache"), { recursive: true });
    fs.mkdirSync(output);
    fs.writeFileSync(path.join(input, "handler.py"), "def lambda_handler(e, c): return e\n");
    fs.writeFileSync(path.join(input, "board_x.py"), "");
    fs.writeFileSync(path.join(input, "receivables.sql"), "CREATE TABLE t (id int);\n");
    fs.writeFileSync(path.join(input, "README.md"), "not copied");
    fs.writeFileSync(path.join(input, "fonts", "NotoSans-Regular.ttf"), "ttf");
    fs.writeFileSync(path.join(input, "brand", "logo.png"), "png");
    fs.writeFileSync(path.join(input, "brand", "__pycache__", "x.pyc"), "pyc");
    fs.writeFileSync(path.join(input, "__pycache__", "handler.cpython-312.pyc"), "pyc");

    const script = DOCKER_BUNDLE_SCRIPT.split("/asset-output").join(output);
    const run = spawnSync("bash", ["-c", script], { cwd: input, encoding: "utf8" });
    expect(run.stderr).toBe("");
    expect(run.status).toBe(0);

    const listing = fs
      .readdirSync(output, { recursive: true })
      .map(String)
      .sort();
    expect(listing).toEqual([
      "board_x.py",
      "brand",
      path.join("brand", "logo.png"),
      "fonts",
      path.join("fonts", "NotoSans-Regular.ttf"),
      "handler.py",
      "receivables.sql",
    ]);
  });
});
