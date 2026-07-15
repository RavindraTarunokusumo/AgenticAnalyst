interface EmptyStateProps {
  message: string
}

export function EmptyState({ message }: EmptyStateProps) {
  return (
    <div className="px-4 py-6 text-center text-sm text-slate-400">
      {message}
    </div>
  )
}
