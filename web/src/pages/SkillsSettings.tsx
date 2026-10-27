import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useEffect, useState } from 'react'
import { fetchSkills, resetSkill, saveSkill, type Skill } from '../api'

const TITLES: Record<Skill['step'], { title: string; help: string }> = {
  planner: {
    title: 'Plan generation',
    help: 'Must keep the "## Mode: default" and "## Mode: reopened" sections.',
  },
  implementer: { title: 'Implementation', help: 'Instructions for the AI that writes the code.' },
  reviewer: { title: 'Code review', help: 'Instructions for the AI that reviews the branch.' },
  feedback: {
    title: 'Review feedback',
    help: 'Instructions for the AI that makes the edits you ask for on the Changes page.',
  },
}

function SkillEditor({ initial }: { initial: Skill }) {
  const [skill, setSkill] = useState(initial)
  const [text, setText] = useState(initial.content)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const { title, help } = TITLES[skill.step]

  async function run(action: () => Promise<Skill>) {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const next = await action()
      setSkill(next)
      setText(next.content)
      setSaved(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h6" component="h2">
            {title}
          </Typography>
          <Chip
            size="small"
            label={skill.customized ? 'Customised' : 'Default'}
            color={skill.customized ? 'primary' : undefined}
            variant="outlined"
          />
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">
        {help} Every step is always told to read the repo&apos;s AGENTS.md and
        .github/copilot-instructions.md first.
      </Typography>
      <TextField
        label={`${title} skill`}
        multiline
        minRows={10}
        maxRows={24}
        fullWidth
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setSaved(false)
        }}
        slotProps={{ htmlInput: { style: { fontFamily: 'monospace', fontSize: 13 } } }}
      />
      {error && <Alert severity="error">{error}</Alert>}
      {saved && <Alert severity="success">Saved.</Alert>}
      <Stack direction="row" spacing={1}>
        <Button
          variant="contained"
          disabled={busy || text === skill.content || !text.trim()}
          onClick={() => run(() => saveSkill(skill.step, text))}
        >
          Save
        </Button>
        <Button
          disabled={busy || !skill.customized}
          onClick={() => run(() => resetSkill(skill.step))}
        >
          Reset to default
        </Button>
      </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

export default function SkillsSettings() {
  const [skills, setSkills] = useState<Skill[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSkills().then(setSkills, (e: Error) => setError(e.message))
  }, [])

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        AI skills
      </Typography>
      <Typography color="text.secondary">
        Each step uses a built-in skill by default. Edit one to use your own instead; reset to go
        back to the built-in version.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {skills?.map((s) => <SkillEditor key={s.step} initial={s} />)}
    </Stack>
  )
}
