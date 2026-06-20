import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Petal',
  description: 'Workspace-scoped Python dependency manager for ROS2',
  base: '/petal/',
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    logo: '🌱',
    siteTitle: 'Petal',
    nav: [
      { text: 'Philosophy', link: '/philosophy' },
      { text: 'Guide', link: '/getting-started' },
      { text: 'CLI', link: '/cli' },
      { text: 'Changelog', link: '/changelog' }
    ],
    sidebar: [
      {
        text: 'Overview',
        items: [
          { text: 'Home', link: '/' },
          { text: 'Philosophy', link: '/philosophy' },
          { text: 'Getting started', link: '/getting-started' }
        ]
      },
      {
        text: 'Using Petal',
        items: [
          { text: 'Concepts', link: '/concepts' },
          { text: 'CLI reference', link: '/cli' },
          { text: 'Colcon integration', link: '/colcon' }
        ]
      },
      {
        text: 'Project',
        items: [
          { text: 'Agent skill', link: '/agent-skill' },
          { text: 'Development', link: '/development' },
          { text: 'Changelog', link: '/changelog' }
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/matthewyjiang/petal' }
    ],
    search: {
      provider: 'local'
    },
    editLink: {
      pattern: 'https://github.com/matthewyjiang/petal/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    },
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © Matthew Jiang'
    }
  }
})
