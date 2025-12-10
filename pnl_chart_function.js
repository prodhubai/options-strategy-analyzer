// Replacement P&L Chart Function
// Copy this entire function into index.html to replace the old renderPnLChart

function renderPnLChart(s) {
  console.log('renderPnLChart called with:', s)
  
  // Update modal header
  pnlModalTitle.textContent = `${s.symbol} - ${s.strategy}`
  pnlModalSubtitle.textContent = `Expiry: ${fmtExpiry(s.expiry)} (${s.days_to_expiry} days) | Current: $${fmt2(s.spot)}`

  // Parse strategy data
  const spot = Number(s.spot)
  const credit = Number(s.credit || 0)
  const maxLoss = Number(s.max_loss || 0)
  const shortStrike = parseFloat((s.short_strike || '0').toString().replace(/[pc]/g, '')) || 0
  const longStrike = parseFloat((s.long_strike || '0').toString().replace(/[pc]/g, '')) || 0
  const daysToExpiry = Number(s.days_to_expiry || 21)
  const breakeven = Number(s.breakeven || 0)
  
  // Determine if this is a credit or debit strategy
  const isCredit = credit > 0
  const initialCost = isCredit ? credit : -Math.abs(credit) // Credit = positive, Debit = negative
  
  // Generate time axis (days from today to expiration)
  const daysArray = []
  const dateLabels = []
  const today = new Date()
  
  for(let day = 0; day <= daysToExpiry; day++) {
    daysArray.push(day)
    const futureDate = new Date(today)
    futureDate.setDate(today.getDate() + day)
    if(day === 0) {
      dateLabels.push('Today')
    } else if(day === daysToExpiry) {
      dateLabels.push('Expiry')
    } else if(day % Math.max(1, Math.floor(daysToExpiry / 10)) === 0) {
      dateLabels.push(futureDate.toLocaleDateString('en-US', {month: 'short', day: 'numeric'}))
    } else {
      dateLabels.push('')
    }
  }
  
  // Calculate P&L at expiration for different stock prices
  function calculateExpiryPnL(stockPrice) {
    let pnl = 0
    
    if(s.strategy === 'Bull Put Spread') {
      if(stockPrice >= shortStrike) pnl = credit
      else if(stockPrice <= longStrike) pnl = credit - (shortStrike - longStrike)
      else pnl = credit - (shortStrike - stockPrice)
    }
    else if(s.strategy === 'Bear Call Spread') {
      if(stockPrice <= shortStrike) pnl = credit
      else if(stockPrice >= longStrike) pnl = credit - (longStrike - shortStrike)
      else pnl = credit - (stockPrice - shortStrike)
    }
    else if(s.strategy === 'Iron Condor') {
      const putShort = shortStrike
      const callShort = longStrike
      const spreadWidth = Number(s.spread_width || 5)
      const putLong = putShort - spreadWidth
      const callLong = callShort + spreadWidth
      
      if(stockPrice >= putShort && stockPrice <= callShort) pnl = credit
      else if(stockPrice <= putLong) pnl = credit - spreadWidth
      else if(stockPrice >= callLong) pnl = credit - spreadWidth
      else if(stockPrice < putShort) pnl = credit - (putShort - stockPrice)
      else if(stockPrice > callShort) pnl = credit - (stockPrice - callShort)
    }
    else if(s.strategy === 'Covered Call') {
      const stockGain = stockPrice - spot
      if(stockPrice <= shortStrike) pnl = stockGain + credit
      else pnl = (shortStrike - spot) + credit
    }
    else if(s.strategy === 'Cash Secured Put') {
      if(stockPrice >= shortStrike) pnl = credit
      else pnl = credit - (shortStrike - stockPrice)
    }
    else if(s.strategy === 'Long Call') {
      const premium = Math.abs(credit)
      if(stockPrice > shortStrike) pnl = (stockPrice - shortStrike) - premium
      else pnl = -premium
    }
    else if(s.strategy === 'Bull Call Spread') {
      const debit = Math.abs(credit)
      if(stockPrice >= longStrike) pnl = (longStrike - shortStrike) - debit
      else if(stockPrice <= shortStrike) pnl = -debit
      else pnl = (stockPrice - shortStrike) - debit
    }
    
    return pnl
  }
  
  // Create scenarios with different stock price movements
  const scenarios = [
    { label: `Stock at $${fmt2(spot * 1.10)} (+10%)`, finalPrice: spot * 1.10, color: '#16a34a' },
    { label: `Stock at $${fmt2(spot * 1.05)} (+5%)`, finalPrice: spot * 1.05, color: '#86efac' },
    { label: `Stock at $${fmt2(spot)} (Unchanged)`, finalPrice: spot, color: '#3b82f6' },
    { label: `Stock at $${fmt2(spot * 0.95)} (-5%)`, finalPrice: spot * 0.95, color: '#fbbf24' },
    { label: `Stock at $${fmt2(spot * 0.90)} (-10%)`, finalPrice: spot * 0.90, color: '#dc2626' }
  ]
  
  // Generate datasets
  const datasets = scenarios.map(scenario => {
    const pnlOverTime = daysArray.map(day => {
      if(day === 0) {
        // Day 0: Show initial cost/credit
        return initialCost
      } else if(day === daysToExpiry) {
        // At expiration: Calculate final P&L based on stock price
        return calculateExpiryPnL(scenario.finalPrice)
      } else {
        // In between: Linear progression with time decay
        const timeProgress = day / daysToExpiry
        const expiryPnL = calculateExpiryPnL(scenario.finalPrice)
        
        // Smooth curve from initial to final
        return initialCost + (expiryPnL - initialCost) * Math.pow(timeProgress, 0.8)
      }
    })
    
    return {
      label: scenario.label,
      data: pnlOverTime,
      borderColor: scenario.color,
      backgroundColor: 'transparent',
      borderWidth: 2.5,
      pointRadius: 0,
      fill: false,
      tension: 0.4
    }
  })
  
  // Calculate statistics
  const finalPnLs = datasets.map(d => d.data[d.data.length - 1])
  const maxProfit = Math.max(...finalPnLs)
  const maxLossCalc = Math.min(...finalPnLs)
  
  // Update info grid
  pnlInfoGrid.innerHTML = `
    <div class="info-card">
      <div class="info-label">Initial ${isCredit ? 'Credit' : 'Debit'}</div>
      <div class="info-value" style="color:${isCredit ? '#16a34a' : '#dc2626'}">${isCredit ? '+' : ''}$${fmt2(Math.abs(initialCost))}</div>
      <div class="info-sub">${isCredit ? 'Received' : 'Paid'} at entry</div>
    </div>
    <div class="info-card">
      <div class="info-label">Current Stock</div>
      <div class="info-value">$${fmt2(spot)}</div>
      <div class="info-sub">As of today</div>
    </div>
    <div class="info-card">
      <div class="info-label">Breakeven</div>
      <div class="info-value">$${fmt2(breakeven)}</div>
      <div class="info-sub">At expiration</div>
    </div>
    <div class="info-card">
      <div class="info-label">Max Profit</div>
      <div class="info-value" style="color:#16a34a">+$${fmt2(maxProfit)}</div>
      <div class="info-sub">Best scenario</div>
    </div>
    <div class="info-card">
      <div class="info-label">Max Loss</div>
      <div class="info-value" style="color:#dc2626">${maxLossCalc >= 0 ? '+' : ''}$${fmt2(maxLossCalc)}</div>
      <div class="info-sub">Worst scenario</div>
    </div>
    <div class="info-card">
      <div class="info-label">Days to Expiry</div>
      <div class="info-value">${daysToExpiry}</div>
      <div class="info-sub">Time remaining</div>
    </div>
  `

  // Destroy existing chart
  if(pnlChart) {
    pnlChart.destroy()
  }

  // Create P&L chart
  const ctx = pnlCanvas.getContext('2d')
  
  try {
    pnlChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: dateLabels,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          title: {
            display: true,
            text: `${s.strategy} - P&L Evolution Over ${daysToExpiry} Days`,
            font: { size: 16, weight: 'bold' }
          },
          legend: {
            position: 'top',
            labels: { 
              boxWidth: 12, 
              padding: 10, 
              font: { size: 11 },
              usePointStyle: true
            }
          },
          tooltip: {
            callbacks: {
              title: function(context) {
                const day = daysArray[context[0].dataIndex]
                return context[0].label + ' (Day ' + day + ')'
              },
              label: function(context) {
                const val = context.parsed.y
                return context.dataset.label + ': ' + (val >= 0 ? '+' : '') + '$' + val.toFixed(2)
              }
            }
          }
        },
        scales: {
          x: {
            title: {
              display: true,
              text: 'Time Until Expiration →',
              font: { size: 12, weight: 'bold' }
            },
            grid: {
              color: function(context) {
                if(context.index === 0 || context.index === daysArray.length - 1) return '#64748b'
                return '#e5e7eb'
              },
              lineWidth: function(context) {
                if(context.index === 0 || context.index === daysArray.length - 1) return 2
                return 1
              }
            }
          },
          y: {
            title: {
              display: true,
              text: 'Profit/Loss ($)',
              font: { size: 12, weight: 'bold' }
            },
            ticks: {
              callback: function(value) {
                return (value >= 0 ? '+' : '') + '$' + value.toFixed(2)
              }
            },
            grid: {
              color: function(context) {
                if(context.tick.value === 0) return '#64748b'
                return '#e5e7eb'
              },
              lineWidth: function(context) {
                if(context.tick.value === 0) return 3
                return 1
              }
            }
          }
        }
      },
      plugins: [{
        id: 'todayMarker',
        afterDatasetsDraw: function(chart) {
          const ctx = chart.ctx
          const xAxis = chart.scales.x
          const yAxis = chart.scales.y
          
          // Draw "Today" vertical dotted line
          const todayX = xAxis.getPixelForValue(0)
          ctx.save()
          ctx.strokeStyle = '#2563eb'
          ctx.lineWidth = 2
          ctx.setLineDash([5, 5])
          ctx.beginPath()
          ctx.moveTo(todayX, yAxis.top)
          ctx.lineTo(todayX, yAxis.bottom)
          ctx.stroke()
          ctx.restore()
          
          // Label
          ctx.save()
          ctx.fillStyle = '#2563eb'
          ctx.font = 'bold 11px Inter'
          ctx.textAlign = 'center'
          ctx.fillText('TODAY', todayX, yAxis.top + 15)
          ctx.restore()
        }
      }]
    })
    
    console.log('P&L Chart created successfully')
    
  } catch(error) {
    console.error('Error creating P&L chart:', error)
    pnlInfoGrid.innerHTML += `<div style="color:red; grid-column:1/-1">Error: ${error.message}</div>`
  }

  // Update legend
  pnlLegend.innerHTML = `
    <div class="pnl-legend-item">
      <div class="pnl-legend-color" style="background:#2563eb; height:2px"></div>
      <span><strong>TODAY</strong> - Entry point (${isCredit ? 'Received' : 'Paid'}: ${isCredit ? '+' : ''}$${fmt2(Math.abs(initialCost))})</span>
    </div>
    <div class="pnl-legend-item">
      <div class="pnl-legend-color" style="background:#64748b; height:3px"></div>
      <span><strong>ZERO LINE</strong> - Breakeven at $${fmt2(breakeven)}</span>
    </div>
    <div class="pnl-legend-item">
      <div class="pnl-legend-color" style="background:#16a34a"></div>
      <span>Maximum profit scenario</span>
    </div>
    <div class="pnl-legend-item">
      <div class="pnl-legend-color" style="background:#dc2626"></div>
      <span>Maximum loss scenario</span>
    </div>
  `
}
