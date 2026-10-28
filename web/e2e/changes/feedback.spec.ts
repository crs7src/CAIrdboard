import { expect, test } from '@playwright/test'

const diff = (extra: string) => `diff --git a/src/a.ts b/src/a.ts
index 111..222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,2 +1,${extra ? 3 : 2} @@
 keep
-old line
+new line
${extra}`

test('leave line and general comments, submit them, and see the result', async ({ page }) => {
  let comments: Record<string, unknown>[] = []
  let run: Record<string, unknown> | null = null
  let polls = 0
  let changed = false
  const posted: unknown[] = []

  await page.route('**/api/cards/AB-1/changes', (route) =>
    route.fulfill({
      json: {
        branch: 'AB-1_x',
        base_commit: 'abc',
        commits: [],
        selected_commit: null,
        diff: diff(changed ? '+added by the agent\n' : ''),
      },
    }),
  )
  await page.route('**/api/cards/AB-1/feedback', (route) => {
    if (run?.state === 'running' && ++polls >= 2) {
      run = { ...run, state: 'done', commits: [{ sha: 'a', short: 'a', subject: 's' }], report: 'All done' }
      comments = comments.map((c) => ({ ...c, status: 'resolved', resolved_in: 1 }))
      changed = true
    }
    return route.fulfill({ json: { comments, run } })
  })
  await page.route('**/api/cards/AB-1/feedback/comments', async (route) => {
    const body = route.request().postDataJSON()
    posted.push(body)
    const comment = { id: `c${comments.length + 1}`, status: 'pending', resolved_in: null, created_at: 'now', side: 'new', file: null, line: null, code: null, ...body }
    comments.push(comment)
    await route.fulfill({ status: 201, json: comment })
  })
  await page.route('**/api/cards/AB-1/feedback/submit', (route) => {
    run = { card_key: 'AB-1', version: 1, state: 'running', branch: 'AB-1_x', comments, commits: [], notes: [], report: null, error: null, created_at: 'n', updated_at: 'n' }
    return route.fulfill({ status: 202, json: run })
  })

  await page.goto('/cards/AB-1/changes')
  await expect(page.getByRole('button', { name: 'Submit for changes' })).toBeDisabled()

  await page.getByRole('button', { name: 'Comment on line 2' }).click()
  await page.getByLabel('Your comment on line 2').fill('Why rename this?')
  await page.getByLabel('File diff').getByRole('button', { name: 'Add comment' }).click()
  await expect(page.getByLabel('File diff').getByText('Why rename this?')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for changes' })).toBeEnabled()

  await page.getByLabel('General comment').fill('Add a test too')
  await page.getByRole('complementary').getByRole('button', { name: 'Add comment' }).click()
  await expect(page.getByText('Pending comments (2)')).toBeVisible()
  expect(posted).toEqual([
    { text: 'Why rename this?', file: 'src/a.ts', line: 2, side: 'new', code: 'new line' },
    { text: 'Add a test too' },
  ])

  await page.getByRole('button', { name: 'Submit for changes' }).click()
  await expect(page.getByText(/An AI is making the requested changes/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for changes' })).toBeDisabled()

  await expect(page.getByText(/Changes made \(1 commit\)/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Pending comments (0)')).toBeVisible()
  await expect(page.getByText('added by the agent')).toBeVisible()
  await page.getByRole('button', { name: 'Resolved (2)' }).click()
  await expect(page.getByText('Add a test too')).toBeVisible()
})
