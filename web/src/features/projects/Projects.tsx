import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Link from '@mui/material/Link'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked'
import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  AI_PROVIDER_LABELS,
  checkRepoHost,
  createProject,
  deleteProject,
  fetchAiProviders,
  fetchProject,
  fetchProjects,
  updateProject,
  type AiProvider,
  type AiProviderId,
  type Project,
  type ProjectCard,
  type ProjectInput,
  type SetupItem,
} from '../../api'
import FolderPicker from '../../shared/FolderPicker'
import { LABELS } from '../../shared/hosts'

type Kind = 'jira_gitlab' | 'jira_github' | 'github'

const KINDS: Record<Kind, string> = {
  jira_gitlab: 'Jira + GitLab',
  jira_github: 'Jira + GitHub',
  github: 'GitHub only',
}

function kindOf(p: Project): Kind {
  if (!p.jira) return 'github'
  return p.host.provider === 'github' ? 'jira_github' : 'jira_gitlab'
}

function stage(c: ProjectCard): string {
  if (c.review_state === 'clean') return c.test_state === 'running' ? 'Testing' : 'Reviewed'
  if (c.review_state === 'fixed') return 'Needs another review'
  if (c.review_state === 'running') return 'Reviewing'
  if (c.implementation_state === 'completed') return 'Implemented'
  if (c.implementation_state === 'running') return 'Implementing'
  if (c.implementation_state === 'failed') return 'Implementation failed'
  if (c.plan_state === 'approved') return 'Plan approved'
  if (c.plan_state === 'ready') return 'Plan awaiting approval'
  if (c.plan_state === 'running') return 'Planning'
  if (c.plan_state) return `Plan ${c.plan_state}`
  return 'No plan'
}

const GROUPS = ['In Progress', 'To Do', 'In Review/Done'] as const

function groupOf(c: ProjectCard): (typeof GROUPS)[number] {
  if (!c.eligible) return 'In Review/Done'
  return c.plan_state ? 'In Progress' : 'To Do'
}

function settingsLink(project: Project, item: SetupItem): string | null {
  if (item.id === 'jira') return '/settings/jira'
  if (item.id === 'tests') return '/settings/test-apps'
  if (item.id === 'ai') return '/settings/ai-providers'
  if (item.id === 'host_credentials' && project.host.provider) return `/settings/${project.host.provider}`
  return null
}

function CardList({ cards, warning }: { cards: ProjectCard[]; warning: string | null }) {
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2">Cards</Typography>
      {warning && (
        <Alert severity="warning" role="note">
          {warning}
        </Alert>
      )}
      {cards.length === 0 && !warning && (
        <Typography variant="body2" color="text.secondary">
          No cards
        </Typography>
      )}
      {GROUPS.map((group) => {
        const rows = cards.filter((c) => groupOf(c) === group)
        if (rows.length === 0) return null
        return (
          <div key={group}>
            <Typography variant="caption" color="text.secondary">
              {group}
            </Typography>
            <List dense disablePadding aria-label={group}>
              {rows.map((c) => (
                <ListItem key={c.key} disableGutters secondaryAction={<Chip size="small" label={stage(c)} />}>
                  <ListItemText
                    primary={
                      <>
                        <Link component={RouterLink} to={`/cards/${c.key}`}>
                          {c.key}
                        </Link>{' '}
                        {c.summary}
                      </>
                    }
                    secondary={c.status}
                    sx={{ pr: 18 }}
                  />
                </ListItem>
              ))}
            </List>
          </div>
        )
      })}
    </Stack>
  )
}

interface FormProps {
  project: Project | null
  onClose: () => void
  onSaved: (p: Project) => void
}

function ProjectForm({ project, onClose, onSaved }: FormProps) {
  const editing = project !== null
  const [name, setName] = useState(project?.name ?? '')
  const [kind, setKind] = useState<Kind>(project ? kindOf(project) : 'jira_gitlab')
  const [key, setKey] = useState(project?.key ?? '')
  const [repo, setRepo] = useState(project?.repo_path ?? '')
  const [hostPath, setHostPath] = useState(project?.host.source === 'override' ? (project.host.path ?? '') : '')
  const [aiProvider, setAiProvider] = useState<AiProviderId | ''>(project?.ai_provider ?? '')
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAiProviders().then(setProviders, () => setProviders([]))
  }, [])
  const defaultProvider = providers.find((p) => p.is_default)

  const jira = kind !== 'github'
  const provider = kind === 'jira_gitlab' ? 'gitlab' : 'github'
  const valid =
    name.trim() && repo.trim() && (!jira || editing || key.trim()) && (jira || hostPath.trim())

  async function submit() {
    setBusy(true)
    setError(null)
    const path = hostPath.trim()
    const input: ProjectInput = {
      name: name.trim(),
      repo_path: repo.trim(),
      key: jira ? key.trim() : null,
      jira_enabled: jira,
      provider: path ? provider : null,
      host_path: path || null,
      ai_provider: aiProvider || null,
    }
    try {
      onSaved(editing ? await updateProject(project.key, input) : await createProject(input))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog open fullWidth maxWidth="sm" onClose={onClose}>
      <DialogTitle>{editing ? `Edit ${project.name}` : 'Add project'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Project name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField
            select
            label="Type"
            value={kind}
            disabled={editing && !project.jira}
            onChange={(e) => setKind(e.target.value as Kind)}
          >
            {Object.entries(KINDS).map(([k, label]) => (
              <MenuItem key={k} value={k} disabled={editing && project.jira && k === 'github'}>
                {label}
              </MenuItem>
            ))}
          </TextField>
          {jira && (
            <TextField
              label="Jira project key"
              helperText="The prefix of the card keys, like ABC for ABC-123."
              value={key}
              disabled={editing}
              onChange={(e) => setKey(e.target.value.toUpperCase())}
            />
          )}
          <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <TextField
              label="Repo path"
              helperText="Absolute path of the local clone the AI works in."
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              sx={{ flex: 1 }}
            />
            <Button sx={{ mt: 1 }} onClick={() => setPicking(true)}>
              Browse
            </Button>
          </Stack>
          <TextField
            label={`${LABELS[provider]} project path`}
            helperText={
              jira
                ? 'Optional: leave empty to detect it from the origin remote.'
                : 'The GitHub repository, like owner/repo. Its issues become this project\u2019s cards.'
            }
            placeholder={provider === 'github' ? 'owner/repo' : 'group/project'}
            value={hostPath}
            onChange={(e) => setHostPath(e.target.value)}
          />
          <TextField
            select
            label="AI provider"
            value={aiProvider}
            onChange={(e) => setAiProvider(e.target.value as AiProviderId | '')}
            helperText="Anthropic and Google Gemini run every stage."
            slotProps={{ select: { displayEmpty: true } }}
          >
            <MenuItem value="">
              Default{defaultProvider ? ` (${defaultProvider.label})` : ''}
            </MenuItem>
            {Object.entries(AI_PROVIDER_LABELS).map(([id, label]) => (
              <MenuItem key={id} value={id}>
                {label}
              </MenuItem>
            ))}
          </TextField>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
        <FolderPicker
          open={picking}
          initialPath={repo}
          onClose={() => setPicking(false)}
          onSelect={(p) => {
            setRepo(p)
            setPicking(false)
          }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={busy || !valid} onClick={submit}>
          {editing ? 'Save' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function ProjectDetails({
  project,
  onEdit,
  onDeleted,
}: {
  project: Project
  onEdit: () => void
  onDeleted: () => void
}) {
  const [detail, setDetail] = useState<Project | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    fetchProject(project.key).then(setDetail, (e: Error) => setError(e.message))
  }, [project])

  async function check() {
    setError(null)
    setResult(null)
    try {
      const p = await checkRepoHost(project.key)
      setResult(`OK: ${p.path}, default branch ${p.default_branch ?? 'none'}`)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function remove() {
    try {
      await deleteProject(project.key)
      onDeleted()
    } catch (err) {
      setError((err as Error).message)
      setConfirming(false)
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {project.repo_path}
        {project.host.path && ` \u00b7 ${project.host.provider ? LABELS[project.host.provider] : ''} ${project.host.path}`}
      </Typography>
      <List dense disablePadding aria-label="Setup checklist">
        {project.status.map((item) => {
          const to = item.done && item.id !== 'ai' ? null : settingsLink(project, item)
          return (
            <ListItem key={item.id} disableGutters>
              <ListItemIcon sx={{ minWidth: 32 }}>
                {item.done ? <CheckCircleIcon color="success" fontSize="small" /> : <RadioButtonUncheckedIcon fontSize="small" />}
              </ListItemIcon>
              <ListItemText
                primary={item.label}
                secondary={
                  to ? (
                    <Link component={RouterLink} to={to}>
                      {item.done ? 'Change' : 'Set up'}
                    </Link>
                  ) : item.done ? undefined : (
                    'Edit the project to fix this'
                  )
                }
              />
            </ListItem>
          )
        })}
      </List>
      <Stack direction="row" spacing={1}>
        <Button onClick={onEdit}>Edit</Button>
        <Button disabled={!project.host.path} onClick={check}>
          Check host
        </Button>
        <Button color="error" onClick={() => setConfirming(true)}>
          Delete
        </Button>
      </Stack>
      {result && (
        <Alert severity="success" role="status">
          {result}
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {confirming && (
        <Alert
          severity="warning"
          role="note"
          action={
            <>
              <Button color="inherit" size="small" onClick={() => setConfirming(false)}>
                Keep
              </Button>
              <Button color="inherit" size="small" onClick={remove}>
                Confirm delete
              </Button>
            </>
          }
        >
          Delete {project.name}? Its plans, runs and repo are not touched.
        </Alert>
      )}
      {!detail && !error && <CircularProgress size={20} aria-label="Loading cards" />}
      {detail && <CardList cards={detail.cards ?? []} warning={detail.card_warnings} />}
    </Stack>
  )
}

export default function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<{ project: Project | null } | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = () => fetchProjects().then(setProjects, (e: Error) => setError(e.message))

  useEffect(() => {
    load()
  }, [])

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h4" component="h1">
          Projects
        </Typography>
        <Button variant="contained" onClick={() => setForm({ project: null })}>
          Add project
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Set up a project in one place: its repo, its Jira project and its GitLab or GitHub project. Credentials stay under Settings.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {projects?.length === 0 && (
        <Alert severity="info" role="note">
          No projects yet. Add one to get started.
        </Alert>
      )}
      {projects?.map((p) => (
        <Accordion
          key={p.key}
          expanded={expanded === p.key}
          onChange={(_, open) => setExpanded(open ? p.key : null)}
          disableGutters
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} aria-label={p.name}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
              <Typography>{p.name}</Typography>
              <Chip size="small" variant="outlined" label={p.key} />
              {p.jira && <Chip size="small" label="Jira" />}
              {p.host.provider && <Chip size="small" label={LABELS[p.host.provider]} />}
              <Chip
                size="small"
                color={p.status.every((i) => i.done) ? 'success' : 'warning'}
                label={`${p.status.filter((i) => i.done).length}/${p.status.length} set up`}
              />
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
            {expanded === p.key && (
              <ProjectDetails
                project={p}
                onEdit={() => setForm({ project: p })}
                onDeleted={() => {
                  setExpanded(null)
                  load()
                }}
              />
            )}
          </AccordionDetails>
        </Accordion>
      ))}
      {form && (
        <ProjectForm
          project={form.project}
          onClose={() => setForm(null)}
          onSaved={(saved) => {
            setForm(null)
            setExpanded(saved.key)
            load()
          }}
        />
      )}
    </Stack>
  )
}
