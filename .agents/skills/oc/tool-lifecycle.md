# OpenClip capability and tool lifecycle

Read this only when a request needs behavior that is not already available as an
`oc` verb.

## Choose the right execution layer

| Need | Layer | Rule |
| --- | --- | --- |
| Hook selection, cut quality, visual taste, ambiguous planning | Agent | Judgment stays in a worker and is independently verified. |
| Small deterministic file transform with installed local dependencies | Toolbox | Reuse first; author one single-purpose script only for a real gap. |
| Capability used by multiple flows that needs project state, ledger, resume, or stable flags | Built-in `oc` command | Propose a core implementation and release it through OpenClip. |
| Browser automation, remote API, long-running service, or privileged credentials | Dedicated integration | Do not hide it in an unreviewed toolbox script. |

## Toolbox lifecycle

1. Search: `oc --project <P> toolbox list --query <term>`.
2. Reuse a healthy match after reading `toolbox show`.
3. If none fits, dispatch `oc-toolsmith` to author one script.
4. Register only with a self-test that exits zero and prints exactly one JSON object.
5. Run it on representative inputs; a failed script must make `oc toolbox run`
   exit non-zero.
6. Verify any media/image/subtitle/JSON artifact with `oc verify` and an
   independent `oc-verifier` when editorial meaning is involved.
7. Dispatch `oc-tool-auditor`; only a clean re-test plus `--reviewed` may promote
   the tool to shared.
8. After at least three representative runs and 80% success, create a packet:

   ```bash
   oc --project <P> toolbox propose --name <tool> --target toolbox
   # or --target builtin when several flows need a stable core verb
   ```

## External contribution boundary

`toolbox propose` only writes a self-contained proposal directory with the
script, `proposal.json`, and `PR_BODY.md`. It never mutates git or GitHub.

Show the user the proposal summary and ask whether to submit it upstream. Only
after an explicit yes may the orchestrator:

1. create a feature branch;
2. copy/stage only the proposed tool and packet;
3. commit and push without force;
4. create a PR against `Q00/openclip` using `PR_BODY.md`;
5. wait for CI and maintainer review.

Other users receive an accepted shared tool or builtin only after an OpenClip
release. Tell them to run `uv tool upgrade openclip-agent` and
`npx skills update`.
