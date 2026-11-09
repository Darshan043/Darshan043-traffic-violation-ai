import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (this.state.error) return <section className="page-error" role="alert"><h2>This page hit a problem</h2><p>{this.state.error.message}</p><button className="button button-secondary" type="button" onClick={() => this.setState({ error: null })}>Try again</button></section>
    return this.props.children
  }
}
