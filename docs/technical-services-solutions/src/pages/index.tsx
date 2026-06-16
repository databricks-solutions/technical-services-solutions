import {type ReactNode, useState, createContext, useContext, useEffect} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

type ScrollContextType = {
  showUpArrow: boolean;
};

export const ScrollContext = createContext<ScrollContextType>({
  showUpArrow: false,
});

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();

  const scrollToSolutions = () => {
    const element = document.getElementById('solutions');
    if (element) {
      const y = element.getBoundingClientRect().top + window.pageYOffset;
      window.scrollTo({ top: y, behavior: 'smooth' });
    }
  };

  return (
    <header className={styles.heroBanner}>
      <div className={styles.heroContent}>
        <div className={styles.heroText}>
          <Heading as="h1" className={styles.heroTitle}>
            {siteConfig.title}
          </Heading>
          <p className={styles.heroSubtitle}>
            Accelerate your Databricks implementations with ready-to-use solutions,
            best practices, and battle-tested code examples.
          </p>
          <div className={styles.heroButtons}>
            <Link
              className={clsx('button button--lg', styles.outlineButton)}
              to="/docs/intro">
              Overview
            </Link>
            <button
              className={clsx('button button--lg', styles.primaryButton)}
              onClick={scrollToSolutions}>
              Get Started
            </button>
            <Link
              className={clsx('button button--lg', styles.secondaryButton)}
              href="https://github.com/databricks-solutions/technical-services-solutions">
              View on GitHub
            </Link>
          </div>
        </div>
        <div className={styles.heroGraphic}>
          <div className={styles.graphicElement}>
            <svg viewBox="0 0 200 200" className={styles.heroSvg}>
              <defs>
                <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#ff3621" stopOpacity="0.8"/>
                  <stop offset="100%" stopColor="#ff5f46" stopOpacity="0.4"/>
                </linearGradient>
                <linearGradient id="grad2" x1="0%" y1="100%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#2272b4" stopOpacity="0.6"/>
                  <stop offset="100%" stopColor="#8acaff" stopOpacity="0.3"/>
                </linearGradient>
              </defs>
              <polygon points="100,10 190,60 190,140 100,190 10,140 10,60" fill="url(#grad1)" opacity="0.9"/>
              <polygon points="100,30 170,70 170,130 100,170 30,130 30,70" fill="url(#grad2)" opacity="0.8"/>
              <polygon points="100,50 150,80 150,120 100,150 50,120 50,80" fill="#1b3139" opacity="0.9"/>
              <text x="100" y="108" textAnchor="middle" fill="#ffffff" fontSize="24" fontWeight="bold">STS</text>
            </svg>
          </div>
        </div>
      </div>
      <div className={styles.heroWave}>
        <svg viewBox="0 0 1440 120" preserveAspectRatio="none">
          <path
            fill="var(--ifm-background-color)"
            d="M0,64L48,69.3C96,75,192,85,288,80C384,75,480,53,576,48C672,43,768,53,864,64C960,75,1056,85,1152,80C1248,75,1344,53,1392,42.7L1440,32L1440,120L1392,120C1344,120,1248,120,1152,120C1056,120,960,120,864,120C768,120,672,120,576,120C480,120,384,120,288,120C192,120,96,120,48,120L0,120Z"
          />
        </svg>
      </div>
    </header>
  );
}

function StatsSection() {
  return (
    <section className={styles.statsSection}>
      <div className="container">
        <div className={styles.statsGrid}>
          <div className={styles.statItem}>
            <span className={styles.statNumber}>7</span>
            <span className={styles.statLabel}>Solution Categories</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statNumber}>50+</span>
            <span className={styles.statLabel}>Code Examples</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statNumber}>100%</span>
            <span className={styles.statLabel}>Open Source</span>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  const [showUpArrow, setShowUpArrow] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      const solutionsElement = document.getElementById('solutions');
      if (solutionsElement) {
        const rect = solutionsElement.getBoundingClientRect();
        // Show arrow when solutions section is near or at the top of viewport
        setShowUpArrow(rect.top <= 100);
      }
    };

    window.addEventListener('scroll', handleScroll);
    handleScroll(); // Check initial position

    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <ScrollContext.Provider value={{showUpArrow}}>
      <Layout
        title="Home"
        description="Technical Services Solutions - Code examples, demos, and scripts to accelerate Databricks implementations">
        <HomepageHeader />
        <main>
          <StatsSection />
          <HomepageFeatures />
        </main>
      </Layout>
    </ScrollContext.Provider>
  );
}
